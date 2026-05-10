class OCRTransient(Exception):
    """OCR 服务临时异常，可由 Celery 自动重试。"""


class OCRTimeout(OCRTransient):
    """OCR 轮询超过最大等待时间。"""


class OCRFailed(Exception):
    """OCR 服务返回明确失败状态。"""
