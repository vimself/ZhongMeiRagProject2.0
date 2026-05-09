import os
import uuid
import asyncio
import zipfile
import base64
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from concurrent.futures import ThreadPoolExecutor
import shutil
from pydantic import BaseModel

from config import (
    TEMP_DIR, MAX_FILE_SIZE, ALLOWED_EXTENSIONS, 
    API_HOST, API_PORT, API_WORKERS
)
from ocr_processor import PDFOCRProcessor

app = FastAPI(title="DeepSeek OCR API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(TEMP_DIR, exist_ok=True)

processor = PDFOCRProcessor()

executor = ThreadPoolExecutor(max_workers=API_WORKERS)


class ImageInfo(BaseModel):
    name: str
    url: str
    size: int
    width: Optional[int] = None
    height: Optional[int] = None


class ImageListResponse(BaseModel):
    session_id: str
    total: int
    images: List[ImageInfo]


class ImageDataResponse(BaseModel):
    name: str
    base64: str
    mime_type: str
    size: int


class ImagesDataResponse(BaseModel):
    session_id: str
    total: int
    images: List[ImageDataResponse]


def cleanup_temp_files(session_id: str):
    session_dir = os.path.join(TEMP_DIR, session_id)
    if os.path.exists(session_dir):
        shutil.rmtree(session_dir)


def validate_file(file: UploadFile) -> bool:
    if not file.filename:
        return False
    
    file_ext = file.filename.lower().split('.')[-1]
    if file_ext not in ALLOWED_EXTENSIONS:
        return False
    
    return True


async def process_pdf_task(session_id: str, pdf_path: str, output_dir: str):
    try:
        result = processor.process_pdf(pdf_path, output_dir)
        
        status_file = os.path.join(output_dir, 'status.txt')
        with open(status_file, 'w', encoding='utf-8') as f:
            f.write('completed')
        
        return result
    except Exception as e:
        status_file = os.path.join(output_dir, 'status.txt')
        with open(status_file, 'w', encoding='utf-8') as f:
            f.write(f'failed: {str(e)}')
        raise e


@app.get("/")
async def root():
    return {
        "message": "DeepSeek OCR API",
        "version": "1.0.0",
        "endpoints": {
            "/upload": "POST - Upload PDF for OCR processing",
            "/status/{session_id}": "GET - Check processing status",
            "/result/{session_id}": "GET - Download all results as zip",
            "/result/{session_id}/markdown": "GET - Get markdown content",
            "/result/{session_id}/images": "GET - Download all images as zip",
            "/result/{session_id}/images/list": "GET - Get image list with URLs (recommended)",
            "/result/{session_id}/images/base64": "GET - Get all images as base64 JSON",
            "/result/{session_id}/image/{image_name}": "GET - Download single image"
        }
    }


@app.post("/upload")
async def upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not validate_file(file):
        raise HTTPException(status_code=400, detail="Invalid file. Only PDF files are allowed.")
    
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File size exceeds {MAX_FILE_SIZE / (1024*1024):.0f}MB limit.")
    
    session_id = str(uuid.uuid4())
    session_dir = os.path.join(TEMP_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    pdf_path = os.path.join(session_dir, file.filename)
    with open(pdf_path, 'wb') as f:
        f.write(content)
    
    output_dir = os.path.join(session_dir, 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    status_file = os.path.join(output_dir, 'status.txt')
    with open(status_file, 'w', encoding='utf-8') as f:
        f.write('processing')
    
    background_tasks.add_task(process_pdf_task, session_id, pdf_path, output_dir)
    
    return {
        "session_id": session_id,
        "status": "processing",
        "message": "PDF uploaded successfully. Processing started."
    }


@app.get("/status/{session_id}")
async def get_status(session_id: str):
    output_dir = os.path.join(TEMP_DIR, session_id, 'output')
    
    if not os.path.exists(output_dir):
        raise HTTPException(status_code=404, detail="Session not found.")
    
    status_file = os.path.join(output_dir, 'status.txt')
    if not os.path.exists(status_file):
        return {"session_id": session_id, "status": "processing"}
    
    with open(status_file, 'r', encoding='utf-8') as f:
        status = f.read().strip()
    
    return {
        "session_id": session_id,
        "status": status,
        "is_completed": status == 'completed',
        "is_failed": status.startswith('failed')
    }


@app.get("/result/{session_id}")
async def get_result(session_id: str):
    output_dir = os.path.join(TEMP_DIR, session_id, 'output')
    
    if not os.path.exists(output_dir):
        raise HTTPException(status_code=404, detail="Session not found.")
    
    status_file = os.path.join(output_dir, 'status.txt')
    if os.path.exists(status_file):
        with open(status_file, 'r', encoding='utf-8') as f:
            status = f.read().strip()
        
        if status != 'completed':
            if status == 'processing':
                raise HTTPException(status_code=202, detail="Processing is still in progress.")
            else:
                raise HTTPException(status_code=500, detail=f"Processing failed: {status}")
    
    zip_path = os.path.join(TEMP_DIR, f"{session_id}_results.zip")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(output_dir):
            for file in files:
                if file != 'status.txt':
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, output_dir)
                    zipf.write(file_path, arcname)
    
    return FileResponse(
        path=zip_path,
        media_type='application/zip',
        filename=f"{session_id}_results.zip"
    )


@app.get("/result/{session_id}/markdown")
async def get_markdown(session_id: str):
    output_dir = os.path.join(TEMP_DIR, session_id, 'output')
    
    if not os.path.exists(output_dir):
        raise HTTPException(status_code=404, detail="Session not found.")
    
    status_file = os.path.join(output_dir, 'status.txt')
    if os.path.exists(status_file):
        with open(status_file, 'r', encoding='utf-8') as f:
            status = f.read().strip()
        
        if status != 'completed':
            if status == 'processing':
                raise HTTPException(status_code=202, detail="Processing is still in progress.")
            else:
                raise HTTPException(status_code=500, detail=f"Processing failed: {status}")
    
    markdown_path = os.path.join(output_dir, 'result.md')
    if not os.path.exists(markdown_path):
        raise HTTPException(status_code=404, detail="Markdown result not found.")
    
    with open(markdown_path, 'r', encoding='utf-8') as f:
        markdown_content = f.read()
    
    return {
        "session_id": session_id,
        "markdown": markdown_content
    }


@app.get("/result/{session_id}/images")
async def get_images(session_id: str):
    output_dir = os.path.join(TEMP_DIR, session_id, 'output')
    
    if not os.path.exists(output_dir):
        raise HTTPException(status_code=404, detail="Session not found.")
    
    status_file = os.path.join(output_dir, 'status.txt')
    if os.path.exists(status_file):
        with open(status_file, 'r', encoding='utf-8') as f:
            status = f.read().strip()
        
        if status != 'completed':
            if status == 'processing':
                raise HTTPException(status_code=202, detail="Processing is still in progress.")
            else:
                raise HTTPException(status_code=500, detail=f"Processing failed: {status}")
    
    images_dir = os.path.join(output_dir, 'images')
    if not os.path.exists(images_dir):
        raise HTTPException(status_code=404, detail="No images found.")
    
    zip_path = os.path.join(TEMP_DIR, f"{session_id}_images.zip")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(images_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = file
                zipf.write(file_path, arcname)
    
    return FileResponse(
        path=zip_path,
        media_type='application/zip',
        filename=f"{session_id}_images.zip"
    )


@app.get("/result/{session_id}/image/{image_name}")
async def get_single_image(session_id: str, image_name: str):
    output_dir = os.path.join(TEMP_DIR, session_id, 'output')
    
    if not os.path.exists(output_dir):
        raise HTTPException(status_code=404, detail="Session not found.")
    
    image_path = os.path.join(output_dir, 'images', image_name)
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="Image not found.")
    
    return FileResponse(
        path=image_path,
        media_type='image/jpeg'
    )


@app.get("/result/{session_id}/images/list", response_model=ImageListResponse)
async def get_images_list(session_id: str):
    output_dir = os.path.join(TEMP_DIR, session_id, 'output')
    
    if not os.path.exists(output_dir):
        raise HTTPException(status_code=404, detail="Session not found.")
    
    status_file = os.path.join(output_dir, 'status.txt')
    if os.path.exists(status_file):
        with open(status_file, 'r', encoding='utf-8') as f:
            status = f.read().strip()
        
        if status != 'completed':
            if status == 'processing':
                raise HTTPException(status_code=202, detail="Processing is still in progress.")
            else:
                raise HTTPException(status_code=500, detail=f"Processing failed: {status}")
    
    images_dir = os.path.join(output_dir, 'images')
    if not os.path.exists(images_dir):
        return ImageListResponse(session_id=session_id, total=0, images=[])
    
    images = []
    for file in sorted(os.listdir(images_dir)):
        if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
            file_path = os.path.join(images_dir, file)
            file_size = os.path.getsize(file_path)
            
            image_url = f"/result/{session_id}/image/{file}"
            
            images.append(ImageInfo(
                name=file,
                url=image_url,
                size=file_size
            ))
    
    return ImageListResponse(
        session_id=session_id,
        total=len(images),
        images=images
    )


@app.get("/result/{session_id}/images/base64", response_model=ImagesDataResponse)
async def get_images_base64(session_id: str):
    output_dir = os.path.join(TEMP_DIR, session_id, 'output')
    
    if not os.path.exists(output_dir):
        raise HTTPException(status_code=404, detail="Session not found.")
    
    status_file = os.path.join(output_dir, 'status.txt')
    if os.path.exists(status_file):
        with open(status_file, 'r', encoding='utf-8') as f:
            status = f.read().strip()
        
        if status != 'completed':
            if status == 'processing':
                raise HTTPException(status_code=202, detail="Processing is still in progress.")
            else:
                raise HTTPException(status_code=500, detail=f"Processing failed: {status}")
    
    images_dir = os.path.join(output_dir, 'images')
    if not os.path.exists(images_dir):
        return ImagesDataResponse(session_id=session_id, total=0, images=[])
    
    images = []
    mime_map = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif'
    }
    
    for file in sorted(os.listdir(images_dir)):
        file_lower = file.lower()
        if file_lower.endswith(('.jpg', '.jpeg', '.png', '.gif')):
            file_path = os.path.join(images_dir, file)
            file_size = os.path.getsize(file_path)
            
            with open(file_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            ext = os.path.splitext(file_lower)[1]
            mime_type = mime_map.get(ext, 'image/jpeg')
            
            images.append(ImageDataResponse(
                name=file,
                base64=image_data,
                mime_type=mime_type,
                size=file_size
            ))
    
    return ImagesDataResponse(
        session_id=session_id,
        total=len(images),
        images=images
    )


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    session_dir = os.path.join(TEMP_DIR, session_id)
    
    if not os.path.exists(session_dir):
        raise HTTPException(status_code=404, detail="Session not found.")
    
    try:
        shutil.rmtree(session_dir)
        return {
            "session_id": session_id,
            "message": "Session deleted successfully."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT, workers=1)
