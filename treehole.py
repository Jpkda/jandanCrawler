import aiohttp
import asyncio
from bs4 import BeautifulSoup
import configs


async def get_page(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers= configs.get_headers()) as response:
            return await response.text()


async def parse_page(url):
    page_context = await get_page(url)
    soup = BeautifulSoup(page_context, 'html.parser')







if __name__=='__main__':
    url = "https://jandan.net/treehole"
    html = asyncio.run(get_page(url))
    print(html)