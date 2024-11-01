import asyncio
import logging
import tools


async def parse_info(response):
    # all_page_num = response.find('div', class_="page-nav").find_all('li')[-1]
    logging.info(f"全部页面数量是:{response}")








async def main(start_url):
    response = await tools.request_page(start_url, "http")
    await parse_info(response)


if __name__ == '__main__':
    start_url = "https://jandan.net/bbs#/"
    asyncio.run(main(start_url))