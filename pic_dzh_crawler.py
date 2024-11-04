import logging
from tools import request_page, get_headers
import asyncio




#
# 子网站 https://jandan.net/dzh
# 图片评论接口 https://jandan.net/api/v1/tucao/list/5785631
# 图片当前页接口 https://jandan.net/api/v1/comment/flow_recommend
# 图片下一页接口 https://jandan.net/api/v1/comment/flow_recommend?start=5785565
# 一页20组图片数据
#referer: https://jandan.net/dzh

class Pic:

    def __init__(self, pic_start_api):
        self.pic_start_api = pic_start_api



    async def paser_page(self):
        data = await request_page(self.pic_start_api, "json")
        logging.info(f"返回全部数据{pic_start_api}{data}")

        todo_lists = []
        for item in data.get("data", []):
            imgs = []
            for img in item.get("images"):
                imgs.append(img.get("full_url", ""))
            todo_dict = {
                "pic_id": item.get("id", "未知"),
                "author": item.get("author", "未知"),
                "images": imgs,
                "time": item.get("date", "未知时间"),
                "location": item.get("ip_location", "未知位置"),
                "endorse": item.get("vote_positive", 0),
                "oppose": item.get("vote_negative", 0),
                "reply_comment_count": item.get("reply_comment_count", 0)
            }
            todo_lists.append(todo_dict)

        logging.info(f"单个item数据{todo_lists}")
        return todo_lists





    # async def


    async def run(self):
        await self.paser_page()




if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    pic_start_api = "https://jandan.net/api/v1/comment/flow_recommend"
    pic = Pic(pic_start_api)
    asyncio.run(pic.run())
