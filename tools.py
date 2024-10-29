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


# 保存到hole数据库中
async def save_to_mongo(data):
    client = AsyncIOMotorClient('mongodb://localhost:27017/')
    jandan_hole = client['jandan_hole']
    collection = jandan_hole["hole_content"]

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


if __name__=='__main__':
    test_dict = [{'author': '迟来的秋天', 'time_info': '2024-10-29 17', 'post_text': '今天用了一下湿厕纸，舒服的。😄', 'endorse': '9', 'oppose': '0', 'tucao_count': '0', 'comment': []}]
    asyncio.run(save_to_mongo(test_dict))