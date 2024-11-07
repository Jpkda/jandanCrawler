import logging
from tools import request_page, get_headers
import asyncio


#
# 子网站 https://jandan.net/dzh
# 图片评论接口 https://jandan.net/api/v1/tucao/list/5785631
# 图片当前页接口 https://jandan.net/api/v1/comment/flow_recommend
# 图片下一页接口 https://jandan.net/api/v1/comment/flow_recommend?start=5785565
# 一页20组图片数据
# referer: https://jandan.net/dzh


class Pic:

    def __init__(self, pic_start_url):
        self.pic_start_url = pic_start_url

    @classmethod
    async def parse_itme_page(self, item_id: str) -> list:  # 图片评论接口 https://jandan.net/api/v1/tucao/list/5785631
        base_url = "https://jandan.net/api/v1/tucao/list/"
        item_url = f"{base_url}{item_id}"
        try:
            data = await request_page(item_url, "json")
            item_list = []
            for comment in data.get("comments", []):
                todo_dict = {
                    "author_id": comment.get("id", "未知"),
                    "author": comment.get("author", "未知"),
                    "date": comment.get("date", "未知时间"),
                    "content": comment.get("content", "未知"),
                    "location": comment.get("ip_location", "未知位置"),
                    "endorse": comment.get("vote_positive", 0),
                    "oppose": comment.get("vote_negative", 0),
                }
                item_list.append(todo_dict)
            logging.info(f"单个评论 item数据{item_list}")
            return item_list
        except Exception as e:
            logging.error(f"获取评论数据失败 for {item_id}: {e}")
            return []

    async def parse_page(self):
        try:
            data = await request_page(self.pic_start_url, "json")
            logging.info(f"返回全部数据{pic_start_api}{data}")

            todo_list = []
            last_page_id = None  # 记录最后一个页面id
            for item in data.get("data", []):
                imgs = []
                for img in item.get("images"):
                    imgs.append(img.get("full_url", ""))
                itme_id = item.get("id", "未知")
                sub_data = await self.parse_itme_page(itme_id)  # 获取评论列表
                todo_dict = {
                    "pic_id": itme_id,
                    "author": item.get("author", "未知"),
                    "images": imgs,
                    "time": item.get("date", "未知时间"),
                    "location": item.get("ip_location", "未知位置"),
                    "endorse": item.get("vote_positive", 0),
                    "oppose": item.get("vote_negative", 0),
                    "reply_comment_count": item.get("reply_comment_count", 0),
                    "comments": sub_data
                }
                last_page_id = itme_id
                todo_list.append(todo_dict)
            next_page_base_url = "https://jandan.net/api/v1/comment/flow_recommend?start="
            next_page = f"{next_page_base_url}{last_page_id}"
            logging.info(f"单个item数据{todo_list}")
            return todo_list, next_page
        except Exception as e:
            logging.error(f"获取页面数据失败 for {pic_start_api}: {e}")
            return [], None

    async def run(self):
        visited = set()
        stack = [self.pic_start_url]
        # semaphore = asyncio.Semaphore(max_concurrent_requests)
        while stack:
            current_url = stack.pop()
            if current_url in visited:
                continue
            visited.add(current_url)
            self.pic_start_url = current_url
            all_data, next_url = await self.parse_page()
            if next_url:
                stack.append(next_url)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    pic_start_api = "https://jandan.net/api/v1/comment/flow_recommend"
    pic = Pic(pic_start_api)
    asyncio.run(pic.run())
