import asyncio
import logging
from pymongo.errors import PyMongoError
from tools import Tools
import tools


#
#   主页：https://jandan.net/treehole
#   子页：https://jandan.net/t/5781622
#   子页JSON：https://jandan.net/api/tucao/all/5781622
# TODO 队列最后一页的内容获取失败，队列退出时数据还没处理完成
# TODO 只有一个异步任务运行
# TODO 完成评论数据更新

data_time = None


class TreeHole:
    def __init__(self, start_url):
        self.start_url = start_url
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    @classmethod
    # 解析下一页的链接  return page_link, html_time
    async def parse_next_page(cls, response):
        try:
            page_item = response.find('ol', class_='commentlist').find('li')  # 时间
            time = page_item.find('small').a.text
            # logging.info(f"Parsing time string: {time}")
            html_time = await tools.format_time(time)
            page_next = response.find('div', class_='cp-pagenavi')  # 下一页
            page_link = ""
            if page_next:
                # //jandan.net/treehole/MjAyNDEwMjgtNjQ=#comments
                page_next = page_next.find('a', title='Older Comments').get('href')
                page_link = ''.join(["https:", page_next])
            logging.info(f"下一页链接：{page_link}")
            return page_link, html_time
        except Exception as e:
            logging.error(f"解析下一页链接时出错: {e}")
            return None, []

    # 解析页面内容
    async def parse_page_content(self, response):
        try:
            page_items = response.find('ol', class_='commentlist').findAll('li')
            item_json_links = []  # 页面子页链接
            page_info_all = []
            if not page_items:
                return []

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
                    "tucao_count": page_item.find('a', class_='tucao-btn').text.split('[')[-1].split(']')[0],
                    "comment": None  # 添加空字段， 获取数据后填充
                }

                # 获取子页json数据并合并
                try:
                    item_json = await self.parse_item_json(item_link)
                    todo_dict["comment"] = item_json
                    page_info_all.append(todo_dict)
                except Exception as e:
                    logging.error(f"获取 {item_link} 数据时出错: {e}")

            logging.info(f"树洞信息解析结果：{page_info_all}")
            logging.info(f"页面子页链接：{item_json_links}")
            return list(page_info_all)
        except Exception as e:
            logging.error(f"解析下一页页面内容时出错: {e}")
            return []

    # 获取子页JSON信息
    @classmethod
    async def parse_item_json(cls, url: str):
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

    async def get_next_page(self):
        global data_time
        current_url = self.start_url
        while current_url:
            html = await tools.request_page(current_url, "http")
            if html is None:
                logging.error(f"无法获取:{current_url}页面，程序结束")
                return
            next_url, html_time = await self.parse_next_page(html)
            if data_time is None:  # 如果是第一次运行，就从数据库里获取最后一次的插入时间
                data_time = await tools.find_time()
            if await tools.judge_time(html_time, data_time):  # 判断数据库最后插入时间与网页获取的时间
                yield html
            else:
                logging.info("数据库时间相等与网页时间，程序退出")
                return
            current_url = next_url

    async def get_page_content(self, queue: asyncio.Queue):
        while True:
            response = await queue.get()
            if response is None:  # 结束信号
                queue.task_done()
                break
            try:
                data = await self.parse_page_content(response)
                logging.info(f"插入数据的数据{data}")
                await self.save_to_mongo(data)

            except Exception as e:
                logging.error(f"处理页面时出错: {e}")
            finally:
                queue.task_done()

    @tools.db_collection("jandan_hole", "hole_content")
    async def save_to_mongo(self, data, collection=None):
        try:
            # 异步插入数据
            result = await collection.insert_many(data)
            if result.inserted_ids:
                logging.info(f"成功插入文档，ID: {result.inserted_ids}")
            else:
                logging.warning("插入文档失败，但没有抛出异常。")
        except PyMongoError as e:
            logging.error(f"插入文档时发生错误: {e}")

    async def main(self):
        next_page_queue = asyncio.Queue()
        consumers = [asyncio.create_task(self.get_page_content(next_page_queue)) for _ in range(3)]
        try:
            async for next_url in self.get_next_page():
                await next_page_queue.put(next_url)
        except Exception as e:
            logging.error(f"获取下一页出错: {e}")
            return

        await next_page_queue.join()  # 等待所有任务完成

        for _ in consumers:
            await next_page_queue.put(None)  # 结束信号
        await asyncio.gather(*consumers)


if __name__ == '__main__':
    url = "https://jandan.net/treehole"
    url_json = "https://jandan.net/api/tucao/all/5781622"
    tools = Tools()
    asyncio.run(tools.mongo_time_sort())
    asyncio.run(tools.find_time())
    hole = TreeHole(url)
    asyncio.run(hole.main())
    asyncio.run(tools.mongo_time_sort())
