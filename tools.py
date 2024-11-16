import asyncio
import re
from datetime import datetime, timedelta
from functools import wraps

import aiohttp
from bs4 import BeautifulSoup
import logging

from minio import S3Error
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError
import minio
import io


class Tools:
    sem = asyncio.Semaphore(3)

    def __init__(self):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    def db_collection(self: str, collect: str):
        def decorator(func):
            @wraps(func)
            async def wrapper(cls, *args, **kwargs):
                # 自动传递数据库和集合名
                collection = await cls.mongo_client(self, collect)
                return await func(cls, collection=collection, *args, **kwargs)
            return wrapper
        return decorator

    @classmethod
    async def get_headers(cls, **kwargs) -> dict:
        default_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/129.0.0.0 Safari/537.36',
            'Origin': 'https://jandan.net',
            'Accept': 'application/json',
        }
        # 更新头
        headers = default_headers.copy()
        headers.update(kwargs)
        return headers

    # 修改时间格式
    @classmethod
    async def format_time(cls, time_str: str):
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
    @classmethod
    async def request_page(cls, url: str, response_type: str, **kwargs):
        async with cls.sem:
            async with aiohttp.ClientSession() as session:
                try:
                    # await asyncio.sleep(1)
                    async with session.get(url, headers=await cls.get_headers()) as response:
                        response.raise_for_status()
                        if response_type == "http":
                            html = await response.text()
                            return BeautifulSoup(html, 'html.parser')
                        elif response_type == "image":
                            if response.status == 200:
                                return await response.read()
                        else:
                            return await response.json()
                except aiohttp.ClientError as e:
                    logging.error(f"获取{url}时出错：{e}")
                    return None
                except asyncio.TimeoutError:
                    logging.error(f"请求超时")
                    return None

    @classmethod
    async def mongo_client(cls, data_db: str, collect: str):
        try:
            client = AsyncIOMotorClient('mongodb://localhost:27017/')
            hole = client[data_db]
            collection = hole[collect]
            logging.info(f"成功连接到数据库 {data_db}，集合 {collect}")
            return collection
        except Exception as e:
            logging.error(f"连接数据库失败: {e}")
            raise

    # 返回最大的order_time中的时间
    @classmethod
    @db_collection("jandan_hole", "hole_content")
    async def find_time(cls, collection=None):
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

    # 如果true 网页时间大于数据库时间
    @classmethod
    async def judge_time(cls, html_time, data_time):
        time1 = datetime.strptime(html_time, "%Y-%m-%d %H")
        time2 = datetime.strptime(data_time, "%Y-%m-%d %H")
        logging.info(f"时间：html_time:{html_time},data_time:{data_time}")
        if time1 > time2:
            return True
        else:
            return False

    # 更新数据库排序
    @classmethod
    @db_collection("jandan_hole", "hole_content")
    async def mongo_time_sort(cls, collection=None):
        sort_collection = await collection.find().sort("time_info", 1).to_list(length=None)
        for index, comment in enumerate(sort_collection):
            await collection.update_one(
                {'_id': comment['_id']},  # 根据文档的唯一 ID 更新
                {'$set': {'time_order': index + 1}}  # 设置 sort_order 为 1, 2, 3, ...
            )
        logging.info("排序完成")

    @classmethod
    @db_collection("jandan_hole", "hole_content")
    async def remove_field(cls, field: str, collection=None):
        result = await collection.update_many(
            {},  # 匹配所有文档
            {'$unset': {field: ''}}  # 删除 sort_order 字段
        )
        logging.info(f"删除{field}字段完成")

    @classmethod
    async def minio_client(cls, bucket_name: str):
        minio_client = minio.Minio(
            "192.168.150.102:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            secure=False
        )
        # 检查存储桶是否存在，如果不存在则创建
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
        return minio_client

    @classmethod
    async def upload_img(cls, img_url, bucket_name, object_name):
        client = await cls.minio_client(bucket_name)
        image_data = await cls.request_page(img_url, "image")
        try:
            # 将字节数据转换为 BytesIO 对象
            image_stream = io.BytesIO(image_data)
            image_stream.seek(0)  # 重置流的位置到开始
            client.put_object(
                bucket_name,
                object_name,
                image_stream,
                len(image_data),
                content_type="image/gif",
                metadata={'Content-Disposition': 'inline'}
            )
        except S3Error as e:
            print(f"minio上传错误: {e}")

    # try:
    #     # 读取图片文件
    #     with open(image_path, 'rb') as file_data:
    #         file_size = os.path.getsize(image_path)  # 获取文件大小
    #         # 上传文件
    #         client.put_object(
    #             bucket_name,
    #             object_name,
    #             file_data,
    #             file_size,
    #             content_type="image/gif",
    #             metadata={'Content-Disposition': 'inline'}
    #         )
    #         logging.info(f"Uploaded {object_name} to {bucket_name}.")
    # except minio.error.S3Error as err:
    #     logging.info(f"Error occurred: {err}")

    # 装饰器db_collection 将数据库名和集合名传递给 mongo_client


if __name__ == '__main__':
    test_dict = [
        {'author': '迟来的秋天', 'time_info': '2024-10-29 17', 'post_text': '今天', 'endorse': '9', 'oppose': '0',
         'tucao_count': '0', 'comment': []}]
    image_jpg_path = "test/test_up.jpg"
    image_gif_path = "test/test_up.gif"
    img_url = "https://wx4.moyu.im/large/dedb234agy1hva8zhx3v6j20u00um792.jpg"
    tools = Tools()

    asyncio.run(tools.mongo_time_sort())
    # asyncio.run(tools.find_time())
    # asyncio.run(tools.remove_field("sort_order"))
    # asyncio.run(upload_img(img_url, "jandan-pic", "dedb234agy1hva8zhx3v6j20u00um792.jpg"))
