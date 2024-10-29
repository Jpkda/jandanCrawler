import re

import aiohttp
import asyncio
from bs4 import BeautifulSoup
import logging
from datetime import datetime, timedelta
import configs

#
#   主页：https://jandan.net/treehole
#   子页：https://jandan.net/t/5781622
#   子页JSON：https://jandan.net/api/tucao/all/5781622
#

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
sem = asyncio.Semaphore(3)


async def get_page(url: str, response_type: str):
    async with sem:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=configs.get_headers(), timeout=10) as response:
                    response.raise_for_status()
                    if response_type == "http":
                        html = await response.text()
                        return BeautifulSoup(html, 'html.parser')
                    else:
                        return await response.json()
            except aiohttp.ClientError as e:
                logging.error(f"获取{url}时出错：{e}")
                return None
            except asyncio.TimeoutError:
                logging.error(f"请求超时")
                return None

# 处理时间
async def format_time(time_str: str):
    match = re.match(r'@(\d+)(分钟|小时|天|周) ago', time_str)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)

        # 根据单位创建相应的时间差
        if unit == '周':
            delta = timedelta(weeks=amount)
        elif unit == '天':
            delta = timedelta(days=amount)
        elif unit == '小时':
            delta = timedelta(hours=amount)
        elif unit == '分钟':
            delta = timedelta(minutes=amount)
        else:
            raise ValueError(f"未知的时间单位: {unit}")

        # 计算准确的时间
        now_time = datetime.now() - delta
        formatted_time = now_time.strftime('%Y-%m-%d %H')
        logging.info(f"时间：{formatted_time}")
        return formatted_time
    else:
        raise ValueError("输入格式不正确")


async def parse_next_page(response):
    try:
        page_nexts = response.find('div', class_='cp-pagenavi')
        page_link = ""
        if page_nexts:
            page_next = page_nexts.find('a', title='Older Comments').get(
                'href')  # //jandan.net/treehole/MjAyNDEwMjgtNjQ=#comments
            page_link = ''.join(["https:", page_next])
        logging.info(f"下一页链接：{page_link}")
        return page_link
    except Exception as e:
        logging.error(f"解析下一页链接时出错: {e}")
        return None, []


async def parse_page_content(response):
    try:
        page_items = response.find('ol', class_='commentlist').findAll('li')
        item_json_links = []  # 页面子页链接
        content_list = []  # 树洞发帖详细内容
        if page_items:
            for page_item in page_items:
                # 得到页面所有的子页id，并构造json链接
                text = page_item.get('id')
                page_id = ''.join(filter(str.isdigit, text))
                head = "https://jandan.net/api/tucao/all/"
                item_link = ''.join([head, page_id])
                item_json_links.append(item_link)
                # 得到树洞内容
                time = page_item.find('small').a.text
                logging.info(f"Parsing time string: {time}")
                # await asyncio.sleep(1)
                formatted_time = await format_time(time)
                todo_dict = {
                    'author': page_item.find('strong').text,
                    'time_info': formatted_time,  # 时间处理
                    'post_text': page_item.find('div', class_='text').p.get_text(separator='', strip=True),
                    'endorse': page_item.find('span', class_='tucao-like-container').span.text,
                    'oppose': page_item.find('span', class_='tucao-unlike-container').span.text,
                    'tucao_count': page_item.find('a', class_='tucao-btn').text.split('[')[-1].split(']')[0]
                }
                content_list.append(todo_dict)
                logging.info(f"树洞发帖详细：{todo_dict}")
        logging.info(f"页面子页链接：{item_json_links}")
        # 获取子页json
        detail_tasks = []
        for url in item_json_links:
            detail_tasks.append(parse_item_json(url))
        details = await asyncio.gather(*detail_tasks)
        # 合并详细数据
        comment_list = []
        for content, comment in zip(content_list, details):
            comment_list.append(f"{content}{comment}")

        # for detail in details:
        #     content_list[details.index(detail)]['details'] = detail

        logging.info(f"单页全部数据：{comment_list}")

        return comment_list

    except Exception as e:
        logging.error(f"解析下一页页面内容时出错: {e}")
        return None, []

async def parse_item_json(url):
    data_json = await get_page(url, "json")
    todo_list = []
    for item in data_json.get("tucao", []):
        todo_dict = {
            'user_name': item.get('comment_author', '未知'),
            'user_content': item.get("comment_content", '空'),
            'time': item.get("comment_date", '未知时间'),
            'location': item.get("ip_location", '未知位置'),
            'endorse': item.get("vote_positive", 0),
            'oppose': item.get("vote_negative", 0),
        }
        todo_list.append(todo_dict)
    logging.info(f"吐槽链{todo_list}")
    return todo_list


async def producer( start_url: str):
    url = start_url
    while url:
        # await queue.put(url)
        html = await get_page(url, "http")

        if html is None:
            logging.error("无法获取起始页面，程序结束")
            return
        yield html
        next_url = await parse_next_page(html)
        url = next_url


async def consumer(queue: asyncio.Queue):
    while True:
        response = await queue.get()
        if response is None:
            queue.task_done()
            break
        try:
            await parse_page_content(response)
        except Exception as e:
            logging.error(f"处理页面时出错: {e}")
        finally:
            queue.task_done()


async def main(start_url: str):
    next_page_queue = asyncio.Queue()
    consumers = [asyncio.create_task(consumer(next_page_queue)) for _ in range(3)]
    try:
        async for response in producer(start_url):
            await next_page_queue.put(response)
    except Exception as e:
        logging.error(f"生产者出错: {e}")
        return

    await next_page_queue.join()  # 等待所有任务完成

    for _ in consumers:
        await next_page_queue.put(None)  # 结束信号
    await asyncio.gather(*consumers)


if __name__ == '__main__':
    url = "https://jandan.net/treehole"
    url_json = "https://jandan.net/api/tucao/all/5781622"

    # asyncio.run(parse_page(url))
    # asyncio.run(paser_json(url_json))
    logging.basicConfig(level=logging.INFO)
    # asyncio.run(format_time('@30分钟 ago'))
    asyncio.run(main(url))
