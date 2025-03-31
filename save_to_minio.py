import asyncio
import aiohttp
from minio import Minio
from io import BytesIO
from tools import mongo_client
import logging
import random
import json

# TODO 尝试使用消息队列解耦图片处理逻辑
# 思路一 在图片下载和上传之前，检查图片的哈希值，MD5，UUID或者图片的唯一标识符，上传后，将图片的标识存入 Redis 或 MongoDB 的专门集合中
# low 在图片下载并上传完成后，添加一个键保存到对应的文档里面，作为状态， （图片可能有重复）


class SaveToMinio:
    def __init__(self, config_file="save_to_minio_config.json"):
        with open(config_file, "r") as file:
            config = json.load(file)
        logging.basicConfig(level=logging.INFO)

        # 每次获取的图片数量
        self.batch_size = config.get("pic_batch_size", 10)
        # minio 桶名称
        self.bucket_name = config.get("minio_bucket_name", "test_save")
        # 图片下载并发数量
        num = config.get("pic_semaphore", 6)
        self.semaphore = asyncio.Semaphore(num)
        # 图片重下次数
        self.retries = config.get("retries", 3)
        # 退避因子
        self.backoff_factor = config.get("backoff_factor", 1.0)

        minio_endpoint = config.get("minio_endpoint", "")
        access_key = config.get("minio_access_key", "")
        secret_key = config.get("minio_secret_key", "")
        self.minio_client = Minio(minio_endpoint,
                                  access_key=access_key,
                                  secret_key=secret_key,
                                  secure=False)

        self.pic_upload_status_key = config.get("pic_upload_status_key", "upload_status")
        self.pic_images_key = config.get("pic_images_key", "images")
        self.document_mian_id_key = config.get("document_mian_id_key", "_id")

        self.headers = config.get("headers", {})

        self.collection = None
        self.mongo_db_name = config.get("mongo_db_name", "")
        self.mongo_collection_name = config.get("mongo_collection_name", "")

        self._ensure_bucket_exists()

    # 检查MinIO的桶是否存在， 如果不存在则创建
    def _ensure_bucket_exists(self):
        if not self.minio_client.bucket_exists(self.bucket_name):
            self.minio_client.make_bucket(self.bucket_name)
            logging.info(f"桶：{self.bucket_name} 创建成功")
        else:
            logging.info(f"桶：{self.bucket_name} 已存在")

    # 图片下载
    async def fetch_image(self, img_url: str):
        for attempt in range(self.retries):
            async with self.semaphore:
                try:
                    img_data = await self._fetch_img_data(img_url)
                    if img_data:
                        logging.info(f"图片 {img_url} 下载成功")
                        return img_data
                except Exception as e:
                    wait_time = await self._get_backoff_time(attempt)
                    logging.error(f"链接{img_url}请求失败，第{attempt + 1}次尝试,错误{str(e)}，将在{wait_time}s后重试")
                    # 使用指数来退避等待
                    await asyncio.sleep(wait_time)
        logging.error(f"链接 {img_url} 下载失败，重试次数已达上限")
        return None

    # 图片下载
    async def _fetch_img_data(self, img_url: str):
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                async with session.get(img_url, timeout=aiohttp.
                        ClientTimeout(total=10, connect=5, sock_connect=5)) as response:
                    if response.status == 200:
                        img_data = await response.read()
                        return img_data
                    else:
                        logging.error(f"链接 {img_url} 下载失败，状态码：{response.status}")
            except aiohttp.ClientError as e:
                logging.error(f"链接：{img_url}请求异常:{str(e)}")
        return None

    async def _get_backoff_time(self, attempt: int) -> float:
        # 限制最大等待时间是10s
        return min(self.backoff_factor * (2 ** attempt) + random.uniform(0, 1), 10)

    # 上传图片到MinIO
    async def upload_to_minio(self, img_url: str, object_name: str, doc_id: str, img_index: int):
        image_data = await self.fetch_image(img_url)
        if image_data:
            file_bytes = BytesIO(image_data)
            self.minio_client.put_object(
                self.bucket_name,
                object_name,
                file_bytes,
                len(image_data),
                content_type=f"image/{object_name.split('.')[-1]}",  # 获取后缀
                metadata={'Content-Disposition': 'inline'}
            )

            await self._update_upload_status(doc_id, img_index, True, object_name)
        else:
            await self._update_upload_status(doc_id, img_index, False, object_name)

    async def _update_upload_status(self, doc_id: str, img_index: int, status: bool, object_name: str):
        # 更改mongodb文档图片下载状态
        try:
            update_result = await self.collection.update_one(
                {self.document_mian_id_key: doc_id},
                {"$set": {f"{self.pic_upload_status_key}.{img_index}": status}}
            )
            if update_result.modified_count > 0:
                logging.info(f"文档 {doc_id} 上传状态更新成功:{object_name}标记为已上传")
            else:
                logging.info(f"文档 {doc_id} 上传状态更新失败: {object_name}标记为上传失败")
        except Exception as e:
            logging.error(f"更新{doc_id}失败")

    async def process_images_batch(self, batch_urls: list, batch_docs: list):
        tasks = []
        for i, (image_url, doc) in enumerate(zip(batch_urls, batch_docs)):
            pic_name = image_url.split('/')[-1]
            tasks.append(self.upload_to_minio(image_url, pic_name, doc[self.document_mian_id_key], i))
        await asyncio.gather(*tasks)

    async def process_images(self):
        skip = 0
        while True:
            # 等待 find() 方法的返回结果
            self.collection = await mongo_client(data_db=self.mongo_db_name, collect=self.mongo_collection_name)
            cursor = self.collection.find().skip(skip).limit(self.batch_size)

            # 等待查询结果并将其转为列表
            batch = await cursor.to_list(length=self.batch_size)
            if not batch:
                logging.info("图片链接全部获取完毕")
                break
            # 提取每个文档中的 'images' 列表中的所有链接
            img_urls = []
            batch_docs = []

            for item in batch:
                if self.pic_upload_status_key in item:
                    for idx, status in enumerate(item[self.pic_upload_status_key]):
                        if status is False:
                            img_urls.append(item[self.pic_images_key][idx])
                            batch_docs.append(item)
                else:
                    img_urls.extend(item[self.pic_images_key])
                    batch_docs.extend([item] * len(item[self.pic_images_key]))

            # 调用处理批次的异步方法
            await self.process_images_batch(img_urls, batch_docs)
            skip += self.batch_size

    async def main(self):
        await self.process_images()


if __name__ == '__main__':
    asyncio.run(SaveToMinio().main())
