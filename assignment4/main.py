# to run the script with FastAPI: fastapi dev main.py
# to run the script with uvicorn with fastapi at port 55722: uvicorn main:app --host 0.0.0.0 --port 55722

# import the Fast API package
from fastapi import FastAPI,HTTPException
from datetime import date
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId  #  引入 ObjectId 用于转换
import json
import httpx  # type: ignore # 异步 HTTP 请求库
from typing import List
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse
from bson import Binary
import os
#from .models import messages_collection


# for testing, you can update this one to your student ID
student_list = ["1155219390"] 

MONGO_URL = "mongodb+srv://jzr:12345@cluster0.nqs0n.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

# define a Fast API app and MongoDB client
app = FastAPI()
client = AsyncIOMotorClient(MONGO_URL)
db = client.assignment_db  
chatrooms_collection = db["chatrooms"]
messages_collection = db["messages"]
file_collection = db["files"]

router = APIRouter() 

# 转换 MongoDB 文档中的 ObjectId 为字符串
def convert_object_id(document):
    document["_id"] = str(document["_id"])
    return document

# define a route, binding a function to a URL (e.g. GET method) of the server
@app.get("/")
async def root():
  return {"message": "Hello World"}  # the API returns a JSON response

class Message(BaseModel):
    message: str
    message_time: str
    name: str
    file_uri: str = None  # 新增 file_uri 字段，可以为 None


# 定义根路由
@app.get("/")
async def root():
    return {"message": "Hello World"}  # 返回简单的JSON响应
 
@app.get("/get_chatrooms/")
async def get_chatroom():

       try:
        # 从 chatrooms 集合中查询所有数据，最多获取 100 条
        chatrooms = await chatrooms_collection.find().to_list(100)
        chatrooms = [convert_object_id(chatroom) for chatroom in chatrooms]
        return JSONResponse(content=jsonable_encoder({"data": chatrooms, "status": "OK"}))
       except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Define a route to get chatrooms from MongoDB
@app.get("/get_messages/")
async def get_messages(chatroom_id: int):
    try:
        # 查询数据库中的消息
        messages = await messages_collection.find({"chatroom_id": chatroom_id}).to_list(100)
        
        # 转换每条消息的 _id 字段
        messages = [convert_object_id(message) for message in messages]
        
        # 构建返回的消息数据
        for message in messages:
            # 这里假设你的数据库中存储了文件路径（如果有的话）
            if "file_uri" not in message:
                message["file_uri"] = None  # 如果没有文件，设置为 None

        # 返回响应
        return JSONResponse(content=jsonable_encoder({"data": {"messages": messages}, "status": "OK"}))

    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)}, status_code=500)


@app.post("/send_message/")
async def send_message(request: Request):  
    item = await request.json()

    # Validate inputs
    if "chatroom_id" not in item or "user_id" not in item or "name" not in item or "message" not in item:
        return JSONResponse(content=jsonable_encoder({"status": "ERROR", "message": "Missing required fields"}))

    if len(item["name"]) > 20 or len(item["message"]) > 200:
        return JSONResponse(content=jsonable_encoder({"status": "ERROR", "message": "Name or message exceeds length limits"}))

    # Insert message into the database (including file_url if provided)
    await messages_collection.insert_one(item)

    return JSONResponse(content=jsonable_encoder({"status": "OK"}))

@app.post("/upload_file/")
async def upload_file(file: UploadFile = File(...)):
    try:
        # 获取文件内容并转为二进制
        file_content = await file.read()
        
        if len(file_content) > 16 * 1024 * 1024:  # 限制文件大小为 16MB
            return JSONResponse(content={"status": "ERROR", "message": "File size exceeds 16MB limit"}, status_code=400)
        
        # 将文件存储为二进制数据
        file_data = Binary(file_content)
        
        # 插入消息文档并存储文件数据
        file_doc = {
            "file_name": file.filename,
            "file_data": file_data,
            "file_size": len(file_content),
          
        }

        # 存储到 MongoDB 集合
        result = await file_collection.insert_one(file_doc)

        # 返回文件存储 ID
        return JSONResponse(content={"status": "OK", "file_id": str(result.inserted_id)})

    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)}, status_code=500)


@app.post("/send_message_gpt/")
async def send_message_gpt(request: Request):  
    item = await request.json()

    # Validate inputs
    if "chatroom_id" not in item or "user_id" not in item or "name" not in item or "message" not in item:
        return JSONResponse(content=jsonable_encoder({"status": "ERROR"}))
    
    if len(item["name"]) > 20 or len(item["message"]) > 200:
        return JSONResponse(content=jsonable_encoder({"status": "ERROR"}))

    # Insert message into the database
    await messages_collection.insert_one(item)
    

    # 从请求中获取查询问题和历史记录
    query = item.get("message")  # 假设是请求中的 message 字段
    history = item.get("history", [])  # 假设历史记录也在请求中

    # 使用 httpx 发送异步请求到 api_server
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post('http://localhost:6006/chat', json={
                'query': query,
                'stream': False,
                'history': history,
            })
            
            # 流式读取 http 响应体，按 \0 分割
            if response.status_code == 200:
                for chunk in response.iter_bytes(chunk_size=8192):
                    if chunk:
                        try:
                            data = json.loads(chunk.decode('utf-8'))
                            text = data["text"].rstrip('\r\n')  # 确保末尾无换行
                            # 这里你可以做一些处理，如存储返回的内容或进一步操作
                            response_data = {
                                "chatroom_id": item["chatroom_id"],  # 原始请求中的 chatroom_id
                                "user_id": "999",  # 原始请求中的 user_id
                                "name": "gpt",  # 原始请求中的 name
                                "message": text,  # 返回的响应文本
                                "message_time": item.get("message_time", "unknown"),  # 可以存储一个时间戳
                                "file_url" :"null"
                            }
                            
                            # 存储返回的消息到 messages 集合
                            await messages_collection.insert_one(response_data)

                            print(text)  # 打印输出
                        except json.JSONDecodeError as e:
                            print(f"Error decoding JSON: {e}")
            else:
                raise HTTPException(status_code=response.status_code, detail="Error from api_server")
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Request failed: {e}")

    return JSONResponse(content=jsonable_encoder({"status": "OK"}))