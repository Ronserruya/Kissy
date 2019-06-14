import os
import traceback
import asyncio
from collections import OrderedDict

import aiofiles
from tqdm import tqdm
from bs4 import BeautifulSoup
from aiohttp import ClientSession
from aiohttp.streams import ChunkTupleAsyncStreamIterator

from errors import NoQualityFound
from utils import retryable_get_request, BAR_WIDTH, get_connection, green, red

DEBUG = False
NOVAPLANET_API = 'https://www.novelplanet.me/api/source/'


class VideoQuality:
    P360 = "360p"
    P480 = "480p"
    P720 = "720p"
    P1080 = "1080p"
    P_HIGHEST = "highest"
    P_LOWEST = "lowest"


class Servers:
    NOVA = "nova"
    RAPIDVIDEO = "rapidvideo"
    MP4UPLOAD = "mp4upload"


async def get_rapidvideo_link(session: ClientSession, link: str, quality: str) -> str:
    # link will look like https://www.rapidvideo.com/e/G3HMJUXOY0
    link = link.replace('/e/', '/d/')  # Replace from watch page to download page
    page, status = await retryable_get_request(session, link, 5, 5)

    if status != 200:
        raise RuntimeError("Bad bad")
    soup = BeautifulSoup(page, features="html.parser")
    links = soup.find(class_='title').find_all('a', href=True)
    if quality == VideoQuality.P_HIGHEST:
        desired_link = links[-1]
    else:
        desired_link = next((item for item in links if quality in item.text),
                            None)  # Get the link for the specified quality

        if desired_link is None:
            raise NoQualityFound
    return desired_link['href']


async def get_nova_link(session: ClientSession, link: str, quality: str) -> str:
    # link will look like https://www.novelplanet.me/v/7qv7nqj4lwo
    ep_id = link.split('/')[-1]

    async with session.post(NOVAPLANET_API + ep_id) as resp:
        if resp.status != 200:
            raise RuntimeError("Bad bad")
        response = await resp.json()

    episodes_data = response['data']
    if quality == VideoQuality.P_HIGHEST:
        desired_link = episodes_data[-1]['file']
    else:
        desired_link = next((item['file'] for item in episodes_data if item['label'] == quality),
                            None)  # Get the link for the specified quality

        if desired_link is None:
            raise NoQualityFound

    return desired_link


async def get_mp4upload_link(session: ClientSession, link: str, quality: str) -> str:
    # link will look like https://www.mp4upload.com/embed-jby2ms8ipq5d.html
    link = link.replace('embed-', '')  # Replace from watch page to download page

    # mp4upload only has one quality options
    if quality in [VideoQuality.P_LOWEST, VideoQuality.P_HIGHEST]:
        return link

    page, status = await retryable_get_request(session, link, 5, 5)

    if status != 200:
        raise RuntimeError("Bad bad")
    soup = BeautifulSoup(page, features="html.parser")
    mp4_upload_resolution  = soup.find_all(class_='infoname')[1].next_sibling.text
    mp4_upload_resolution = mp4_upload_resolution .split('x ')[-1] + 'p'  # 1280 x 720 > 720p
    if quality != mp4_upload_resolution:
        raise NoQualityFound

    return link


async def download_episode(session: ClientSession, name: str, link: str,
                           path: str, total_bar: tqdm, pool: asyncio.Queue):
    """Download the episode to local storage"""
    file_target = f'{path}/{name}.mp4'

    try:
        async with get_connection(pool):  # Limit ourself to max concurrent downloads
            if os.path.isfile(file_target):
                raise FileExistsError(f'{name} already exists in the folder')
            req_method = session.post if Servers.MP4UPLOAD in link else session.get
            async with req_method(link) as resp:
                if resp.status != 200:
                    raise RuntimeError(f'Got a bad response from the server for {name}: {resp.status}')

                file_size = int(resp.headers.get('content-length'))

                with tqdm(
                        desc=name, total=file_size, unit='B',
                        unit_scale=True, unit_divisor=1024, leave=False,
                        ncols=BAR_WIDTH) as progress_bar:

                    async with aiofiles.open(f'{path}/{name}', mode='wb') as file:
                        async for chunk, _ in ChunkTupleAsyncStreamIterator(resp.content):
                            await file.write(chunk)
                            progress_bar.update(len(chunk))

                    # Mark success and wait a bit before removing the bar
                    progress_bar.set_postfix_str(green('✔️'))
                    await asyncio.sleep(5)
    except Exception as e:
        tqdm.write(red(f'Failed to download {name} : {e} ❌'))
        if DEBUG:
            tqdm.write(red(''.join(traceback.format_exception(None, e, e.__traceback__))))
        try:
            os.remove(f'{path}/{name}')
        except FileNotFoundError:
            pass
        return False
    finally:
        total_bar.update(1)
    return True

# Ordered since we want to go from the best to worse server
# mp4upload and nova get capcha on kissanime, still can't bypass that
DOWNLOAD_METHODS = OrderedDict()
#DOWNLOAD_METHODS[Servers.NOVA] = get_nova_link
DOWNLOAD_METHODS[Servers.RAPIDVIDEO] = get_rapidvideo_link
#DOWNLOAD_METHODS[Servers.MP4UPLOAD] = get_mp4upload_link
