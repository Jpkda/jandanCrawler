
import aiohttp
import asyncio
from bs4 import BeautifulSoup
import logging
import configs

#
#   主页：https://jandan.net/treehole
#   子页：https://jandan.net/t/5781622
#   子页JSON：https://jandan.net/api/tucao/all/5781622
#

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
sem = asyncio.Semaphore(5)


async def get_page(url: str, response_type: str):
    async with sem:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=configs.get_headers()) as response:
                    response.raise_for_status()

                    if response_type == "http":
                        html = await response.text()
                        return BeautifulSoup(html, 'html.parser')
                    else:
                        return await response.json()
            except Exception as e:
                logging.error(f"获取{url}时出错：{e}")
                return None


async def parse_page(response):
    # 得到下一页连接
    page_nexts = response.find('div', class_='cp-pagenavi')
    page_link = ""
    if page_nexts:
        page_next = page_nexts.find('a', title='Older Comments').get(
            'href')  # //jandan.net/treehole/MjAyNDEwMjgtNjQ=#comments
        page_link = ''.join(["https:", page_next])
    logging.info(f"下一页链接：{page_link}")

    page_items = response.find('ol', class_='commentlist').findAll('li')
    item_json_links = []  # 页面子页链接
    content_list = []  # 树洞发帖详细内容

    for page_item in page_items:
        # 得到页面所有的子页id，并构造json链接
        text = page_item.get('id')
        page_id = ''.join(filter(str.isdigit, text))
        head = "https://jandan.net/api/tucao/all/"
        item_link = ''.join([head, page_id])
        item_json_links.append(item_link)
        # 得到树洞内容
        todo_dict = {
            'author': page_item.find('strong').text,
            'time_info': page_item.find('small').a.text,
            'post_text': page_item.find('div', class_='text').p.get_text(separator='', strip=True),
            'endorse': page_item.find('span', class_='tucao-like-container').span.text,
            'oppose': page_item.find('span', class_='tucao-unlike-container').span.text,
            'tucao_count': page_item.find('a', class_='tucao-btn').text.split('[')[-1].split(']')[0]
        }
        content_list.append(todo_dict)
        logging.info(f"树洞发帖详细：{todo_dict}")
    logging.info(f"页面子页链接：{item_json_links}")

    detail_tasks = [paser_item_json(url) for url in item_json_links]
    details = await asyncio.gather(*detail_tasks)
    # 合并详细数据
    # for result, detail in zip(comment_list, details):
    #     result['details'] = detail

    comment_list = []
    for content, comment in zip(content_list, details):
        comment_list.append(f"{content}{comment}")

    # for detail in details:
    #     content_list[details.index(detail)]['details'] = detail

    logging.info(f"单页全部数据：{comment_list}")

    return page_link, comment_list


async def paser_item_json(url):
    data_json = await get_page(url, "json")
    todo_list = []
    for item in data_json["tucao"]:
        todo_dict = {
            'user_name': item['comment_author'],
            'user_content': item["comment_content"],
            'time': item["comment_date"],
            'location': item["ip_location"],
            'endorse': item["vote_positive"],
            'oppose': item["vote_negative"],
        }
        todo_list.append(todo_dict)
    logging.info(f"吐槽链{todo_list}")
    return todo_list


async def producer(queue: asyncio.Queue, start_url: str):
    url = start_url
    while url:
        await queue.put(url)
        html = await get_page(url, "http")

        if html is None:
            logging.error("无法获取起始页面，程序结束")
            return

        next_url, results = await parse_page(html)
        url = next_url


async def consumer(queue: asyncio.Queue):
    while True:
        url = await queue.get()
        if url is None:
            break
        html = await get_page(url, "http")
        await parse_page(html)
        queue.task_done()


async def mian(start_url: str):
    next_page_queue = asyncio.Queue()
    consumers = [asyncio.create_task(consumer(next_page_queue)) for _ in range(3)]

    await producer(next_page_queue, start_url)

    if next_page_queue.empty():
        logging.error("队列空值，程序结束")
        return

    await next_page_queue.join()

    for _ in consumers:
        await next_page_queue.put(None)
    await asyncio.gather(*consumers)


if __name__ == '__main__':
    url = "https://jandan.net/treehole"
    url_json = "https://jandan.net/api/tucao/all/5781622"

    # asyncio.run(parse_page(url))
    # asyncio.run(paser_json(url_json))
    asyncio.run(mian(url))
