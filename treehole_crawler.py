import asyncio
import logging
import tools


#
#   主页：https://jandan.net/treehole
#   子页：https://jandan.net/t/5781622
#   子页JSON：https://jandan.net/api/tucao/all/5781622
# TODO 队列最后一页的内容获取失败，队列退出时数据还没处理完成


logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
data_time = None

# 解析下一页的链接  return page_link, html_time
async def parse_next_page(response):
    try:
        page_item = response.find('ol', class_='commentlist').find('li')  # 时间
        time = page_item.find('small').a.text
        # logging.info(f"Parsing time string: {time}")
        html_time = await tools.format_time(time)
        page_nexts = response.find('div', class_='cp-pagenavi')  # 下一页
        page_link = ""
        if page_nexts:
            # //jandan.net/treehole/MjAyNDEwMjgtNjQ=#comments
            page_next = page_nexts.find('a', title='Older Comments').get('href')
            page_link = ''.join(["https:", page_next])
        logging.info(f"下一页链接：{page_link}")
        return page_link, html_time
    except Exception as e:
        logging.error(f"解析下一页链接时出错: {e}")
        return None, []


# 解析页面内容
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
                # logging.info(f"Parsing time string: {time}")
                formatted_time = await tools.format_time(time)
                # 处理帖子内容
                post_texts = page_item.find('div', class_='text').find_all('p')
                todo_dict = {
                    "author": page_item.find('strong').text,
                    "time_info": formatted_time,  # 时间处理
                    "post_text": ' '.join([p.get_text(strip=True) for p in post_texts]),
                    "endorse": page_item.find('span', class_='tucao-like-container').span.text,
                    "oppose": page_item.find('span', class_='tucao-unlike-container').span.text,
                    "tucao_count": page_item.find('a', class_='tucao-btn').text.split('[')[-1].split(']')[0]
                }
                content_list.append(todo_dict)
                # logging.info(f"树洞发帖详细：{todo_dict}")
        logging.info(f"页面子页链接：{item_json_links}")
        # 获取子页json
        detail_tasks = []
        for url in item_json_links:
            detail_tasks.append(parse_item_json(url))
        details = await asyncio.gather(*detail_tasks)
        # 合并详细数据
        comment_list = []
        for content, comment in zip(content_list, details):
            content['comment'] = comment
            # logging.info(f"构造字典数据：{content}")
            comment_list.append(content)

        logging.info(f"单页全部数据：{comment_list}")
        return comment_list

    except Exception as e:
        logging.error(f"解析下一页页面内容时出错: {e}")
        return None, []


# 获取子页JSON信息
async def parse_item_json(url: str):
    data_json = await tools.request_page(url, "json")
    todo_list = []
    for item in data_json.get("tucao", []):
        todo_dict = {
            "user_name": item.get('comment_author', "未知"),
            "user_content": item.get("comment_content", "空"),
            "time": item.get("comment_date", "未知时间"),
            "location": item.get("ip_location", "未知位置"),
            "endorse": item.get("vote_positive", 0),
            "oppose": item.get("vote_negative", 0),
        }
        todo_list.append(todo_dict)
    # logging.info(f"吐槽链{todo_list}")
    return todo_list


async def get_next_page(start_url: str):
    global data_time
    url = start_url
    while url:
        html = await tools.request_page(url, "http")
        if html is None:
            logging.error(f"无法获取:{url}页面，程序结束")
            return
        next_url, html_time = await parse_next_page(html)
        if data_time is None:
            data_time = await tools.find_time()
        if await tools.judge_time(html_time, data_time):
            yield html
        else:
            logging.info(f"数据库时间相等与网页时间，程序退出")
            return
        url = next_url


async def get_page_content(queue: asyncio.Queue):
    while True:
        response = await queue.get()
        if response is None:  # 结束信号
            queue.task_done()
            break
        try:
            data = await parse_page_content(response)
            logging.info(f"分页全部数据{data}")
            await tools.save_to_mongo(data)  # 数据插入到数据库
        except Exception as e:
            logging.error(f"处理页面时出错: {e}")
        finally:
            queue.task_done()


async def main(start_url: str):
    next_page_queue = asyncio.Queue()
    consumers = [asyncio.create_task(get_page_content(next_page_queue)) for _ in range(3)]
    try:
        async for next_url in get_next_page(start_url):
            await next_page_queue.put(next_url)
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
    # asyncio.run(format_time('@30分钟 ago'))
    asyncio.run(tools.find_time())
    asyncio.run(main(url))
