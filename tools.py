import asyncio
import re
from datetime import datetime, timedelta
import aiohttp
from bs4 import BeautifulSoup
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError


logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
sem = asyncio.Semaphore(3)


async def get_headers():
    headers ={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/129.0.0.0 Safari/537.36',
        'origin': 'https://jandan.net',
        'Accept': 'application/json',
    }
    return headers


# 修改时间格式
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
        # logging.info(f"时间：{formatted_time}")
        return formatted_time
    else:
        raise ValueError("输入格式不正确")


# 获取页面信息返回response
async def request_page(url: str, response_type: str):
    async with sem:
        async with aiohttp.ClientSession() as session:
            try:
                await asyncio.sleep(1)
                async with session.get(url, headers=await get_headers(), timeout=10) as response:
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


async def mongo_client(data_db:str, collect:str):
    client = AsyncIOMotorClient('mongodb://localhost:27017/')
    hole = client[data_db]
    collection = hole[collect]
    return collection


# 保存到 hole 数据库中
async def save_to_mongo(data):
    collection = await mongo_client("jandan_hole", "hole_content")
    logging.info(f"插入data的信息: {data}")
    try:
        # 异步插入数据
        result = await collection.insert_many(data)
        # 检查插入是否成功
        if result.inserted_ids:
            logging.info(f"成功插入文档，ID: {result.inserted_ids}")
            return result.inserted_ids
        else:
            logging.warning("插入文档失败，但没有抛出异常。")
            return None
    except PyMongoError as e:
        logging.error(f"插入文档时发生错误: {e}")
        return None


# 返回最大的order_time中的时间
async def find_time():
    collection = await mongo_client("jandan_hole", "hole_content")
    try:
        # 查找 sort_order 最大的文档
        max_sort_doc = await collection.find_one(
            {},
            sort=[('time_order', -1)]  # 按 sort_order 降序排列
        )
        if max_sort_doc:
            first_time = max_sort_doc.get('time_info')
            content = max_sort_doc.get('post_text')

            logging.info(f"发布内容：{content}")
            logging.info(f"时间：{first_time}")
            return first_time
        else:
            logging.info(f"没有找到文档")
            return True
    except Exception as e:
        logging.error(f"find_time函数：{e}")
    # finally:
    #     collection.colse()


# 如果true 网页时间大于数据库时间
async def judge_time(html_time, data_time):
    # if data_time is not True:  # 数据库没有数据，就全部爬取
    #     return True
    time1 = datetime.strptime(html_time, "%Y-%m-%d %H")
    time2 = datetime.strptime(data_time, "%Y-%m-%d %H")
    logging.info(f"时间：html_time:{html_time},data_time:{data_time}")
    if time1 > time2:
        return True
    else:
        return False

#更新数据库排序
async def mongo_time_sort():
    collection = await mongo_client("jandan_hole", "hole_content")
    sort_collection = await collection.find().sort("time_info", 1).to_list(length=None)
    for index, comment in enumerate(sort_collection):
        await collection.update_one(
            {'_id': comment['_id']},  # 根据文档的唯一 ID 更新
            {'$set': {'time_order': index + 1}}  # 设置 sort_order 为 1, 2, 3, ...
        )
    logging.info("排序完成")


async def remove_field(field:str):
    collection = await mongo_client("jandan_hole", "hole_content")
    result = await collection.update_many(
        {},  # 匹配所有文档
        {'$unset': {field: ''}}  # 删除 sort_order 字段
    )
    logging.info(f"删除{field}字段完成")



if __name__ == '__main__':
    test_dict = [{'author': '迟来的秋天', 'time_info': '2024-10-29 17', 'post_text': '今天用了一下湿厕纸，舒服的。😄', 'endorse': '9', 'oppose': '0', 'tucao_count': '0', 'comment': []}]
    # asyncio.run(save_to_mongo(test_dict))
    asyncio.run(find_time())
    # asyncio.run(mongo_time_sort())
    # asyncio.run(remove_field("sort_order"))
