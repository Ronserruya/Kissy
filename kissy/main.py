import os
import re
import asyncio
from dataclasses import dataclass

from tqdm import tqdm
import uvloop
from bs4 import BeautifulSoup
from cloudscraper import get_tokens
from aiohttp import ClientSession

from errors import NoQualityFound, NoServerFound
from downloader import VideoQuality, DOWNLOAD_METHODS, download_episode
from utils import retryable_get_request, BAR_WIDTH, green, red

from typing import Tuple, Dict

KISSANIME_URL = "https://kissanime.ru"
ANIME_URL_PATTERN = r"(http|https)://{}/Anime/[^/\s]+$".format(KISSANIME_URL.split("//")[-1])
VIDEO_LINK_PATTERN = r"\$\('#divMyVideo'\).html\('.+src=\"(\S+)"


@dataclass
class DownloadLink:
    name: str
    link: str


def bypass_cloudfront() -> Tuple[Dict[str,str], Dict[str,str]]:
    """Get pass the cloudfront anti-bot protection, and use the keys for all subsequent requests"""
    tokens = get_tokens(KISSANIME_URL)
    headers = {"User-Agent": tokens[1]}
    cookies = tokens[0]

    return headers, cookies


def get_episode_links(soup: BeautifulSoup, start: int, ep_count: int) -> Dict[str, str]:
    """Get the names and links of the episodes"""
    episode_listing_table = soup.find(class_='listing')  # class_ since class is a reserved keyword
    episodes = episode_listing_table.find_all('a', href=True)
    episodes.reverse()  # Episodes are listed from latest to oldest on the site

    """
    Need to find the actual start, a lot of times the first episodes listed are previews or specials,
    so we look for the actual ep name instead of slicing the list blindly.
    """
    first_index = None
    for index, link in enumerate(episodes):
        if f"Episode-{start:03d}" in link['href']:  # :03d pads zeros to the left (2 -> '002')
            first_index = index
            break

    episodes = episodes[first_index:first_index + ep_count]
    episodes_dict = {ep.text.strip().replace(' ', '_'): KISSANIME_URL + ep['href'] for ep in episodes}

    return episodes_dict


def verify_anime_url(url: str) -> bool:
    """Return true if the url matches the expected kissanime url pattern"""
    return re.match(ANIME_URL_PATTERN, url) is not None


async def get_download_link(session: ClientSession, ep_name: str, link: str, quality: str, pb) -> DownloadLink:
    """Download an episode"""
    # Try each server in this order: nova>rapidvideo>mp4upload
    for server, method in DOWNLOAD_METHODS.items():
        # Redirects=False cause kissanime will redirect to the "default" server if the server doesn't exist
        # Or to the "Are you human" captcha page
        page, status = await retryable_get_request(session, link + f"&s={server}", 5, 5, allow_redirects=False)
        if status == 302:
            continue
        video_link = re.findall(VIDEO_LINK_PATTERN, page)[0][:-1]
        pb.update(1)

        try:
            return DownloadLink(ep_name, await method(session, video_link, quality))
        except NoQualityFound:
            pb.write(red(f"Couldn't find {ep_name} in {quality} ❌"))
            raise

    pb.write(red(f"No valid server found for {ep_name} ❌"))
    raise NoServerFound


async def run(anime_url: str) -> None:
    print("Trying to bypass cloudfront protection...")
    headers, cookies = bypass_cloudfront()

    async with ClientSession(headers=headers, cookies=cookies) as session:
        # Verify the cloudfront cookies work
        async with session.get(KISSANIME_URL) as resp:
            if resp.status != 200:
                print('Failed to bypass cloudfront ' + red('❌'))
                exit(1)
            print("Passed cloudfront " + green('✔️'))

            anime_url = anime_url.strip()  # Strip following whitespaces

            async with session.get(anime_url) as resp:
                page = await resp.text()

            soup = BeautifulSoup(page, features="html.parser")
            anime_title = soup.find(class_='bigChar').text.strip().replace(' ', '_')
            print(f'Anime title: {anime_title.replace("_"," ")}')
            try:
                episode_links = get_episode_links(soup, 1, 12)
            except Exception as e:
                print(red("Couldn't get episode links ❌"))
                exit(1)

            if len(episode_links) == 0:
                print(red("Found 0 episodes to download ❌"))
                exit(1)

            print(f'Found {len(episode_links)} episodes to download')

            with tqdm(desc='Collecting download links', total=len(episode_links),
                      bar_format='{desc}: {percentage:3.0f}%|{bar}|{n_fmt}/{total_fmt} {postfix}',
                      ncols=BAR_WIDTH) as progressbar:

                try:
                    tasks = [asyncio.create_task(get_download_link(session, name, link, VideoQuality.P480, progressbar))
                             for name, link in episode_links.items()]
                    download_links = await asyncio.gather(*tasks, return_exceptions=True)
                    links_found = sum([1 for i in download_links if not isinstance(i, Exception)])
                    if links_found == 0:
                        raise RuntimeError("Found no download links")  # Goes to the except block
                except:
                    progressbar.set_postfix_str(red('❌'))
                    tqdm.write(red('Failed to collect download links ❌'))
                    exit(1)
                else:
                    progressbar.set_postfix_str(green('✔️'))

                # Prepare connection pool
                pool = asyncio.Queue()
                max_parallel_downloads = 10
                [await pool.put(i) for i in range(max_parallel_downloads)]

            try:
                os.mkdir(anime_title)
            except FileExistsError:
                pass

            with tqdm(desc='Downloading episodes', total=len(download_links),
                      bar_format='{desc}: |{bar}|{n_fmt}/{total_fmt} {postfix}',
                      ncols=BAR_WIDTH, leave=False) as progressbar:

                tasks = [asyncio.create_task(download_episode(session, ep.name, ep.link, anime_title, progressbar, pool))
                         for ep in download_links if not isinstance(ep, Exception)]
                results = await asyncio.gather(*tasks)
                progressbar.set_postfix_str(green('✔️'))
                await asyncio.sleep(3)

            total_downloaded = sum([1 for res in results if res])
            print(f'\n\nDone, downloaded {total_downloaded}/{len(episode_links)}' + green('✔️'))

#import sys
#sys.stdout = open('/dev/pts/2', 'w')
#sys.stderr = open('/dev/pts/2', 'w')

uvloop.install()  # uvloop is much faster then the default asyncio loop
asyncio.run(run('https://kissanime.ru/Anime/One-Punch-Man-Season-2'))

