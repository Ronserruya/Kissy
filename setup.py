from setuptools import setup, find_packages

#with open("README.md", "r") as fh:
#    long_description = fh.read()

long_description = ""
setup(
    name='kissy',
    version='0.1',
    author="Ron Serruya",
    author_email="ron.serruya@gmail.com",
    description="Kissanime video downloader",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ronserruya/kissy",
    packages=find_packages(),
    include_package_data=True,
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ),
    entry_points='''
    [console_scripts]
    kissy=kissy.cli:main
    ''',
    python_requires='>=3.7',
)
