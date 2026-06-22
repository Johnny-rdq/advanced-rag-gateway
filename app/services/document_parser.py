# 后端 统一文档解析服务 — 根据文件类型自动选择 pdfplumber / LlamaParse（OCR）解析
import os  # 后端 路径和扩展名处理
import io  # 后端 内存字节流
import tempfile  # 后端 临时文件（LlamaParse 需要文件路径）
from app.core.config import settings  # 后端 获取 LlamaCloud API Key


# 后端 LlamaParse 全局实例（懒加载，避免启动时就必须有 API Key）
_llama_parser = None  # 后端 缓存 LlamaParse 实例，None=未初始化，False=不可用


def _get_llama_parser():
    """懒加载 LlamaParse 解析器 — 首次调用时初始化，没有 API Key 则返回 None"""
    global _llama_parser
    if _llama_parser is not None:
        return _llama_parser if _llama_parser is not False else None  # 后端 已初始化则直接返回

    if not settings.LLAMA_CLOUD_API_KEY:  # 后端 没有配 API Key，跳过 LlamaParse
        print("[解析] 未配置 LLAMA_CLOUD_API_KEY，仅使用 pdfplumber 解析 PDF")
        _llama_parser = False
        return None

    try:
        from llama_parse import LlamaParse  # 后端 LlamaIndex 官方文档解析器
        _llama_parser = LlamaParse(
            api_key=settings.LLAMA_CLOUD_API_KEY,
            result_type="markdown",  # 后端 返回 Markdown 格式，保留标题/表格结构
            verbose=False,  # 后端 关闭详细日志
        )
        print("[解析] LlamaParse 就绪（支持扫描件 OCR / DOCX / PPTX / 图片）")
    except ImportError:
        print("[警告] llama-parse 未安装，请执行: pip install llama-parse")
        _llama_parser = False
    except Exception as e:
        print(f"[警告] LlamaParse 初始化失败: {e}")
        _llama_parser = False

    return _llama_parser if _llama_parser is not False else None


def parse_file(file_content: bytes, filename: str) -> str:
    """
    后端 统一文件解析入口
    策略：
      - .txt/.md/.csv → 直接解码文本
      - .pdf → pdfplumber 先尝试提取文本；提取为空（扫描件/图片型PDF）时降级到 LlamaParse OCR
      - .docx/.pptx/.xlsx/.png/.jpg 等 → 全部交给 LlamaParse 处理
    返回解析出的文本，解析失败返回空字符串 ""
    """
    ext = os.path.splitext(filename)[1].lower()  # 后端 提取文件扩展名并转小写

    # ========== 纯文本类文件：直接解码 ==========
    if ext in ('.txt', '.md', '.csv'):
        try:
            return file_content.decode('utf-8', errors='ignore')  # 后端 UTF-8 解码
        except Exception:
            return file_content.decode('gbk', errors='ignore')  # 后端 降级 GBK 解码（Windows 文件常见）

    # ========== PDF 文件：pdfplumber 先试 → LlamaParse 兜底 OCR ==========
    if ext == '.pdf':
        # 第一步：pdfplumber 提取文本（适用于 Word 转的「文本型」PDF）
        pdfplumber_text = ""  # 后端 pdfplumber 提取结果
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                for page in pdf.pages:  # 后端 逐页提取
                    page_text = page.extract_text()  # 后端 pdfplumber 文本提取
                    if page_text:
                        pdfplumber_text += page_text + "\n"
        except Exception:
            pass  # 后端 pdfplumber 失败不报错，降级到 LlamaParse

        if pdfplumber_text.strip():  # 后端 提取到有效文本，直接返回
            return pdfplumber_text

        # 第二步：pdfplumber 没提取到文本 → 判定为扫描件/图片型 PDF，用 LlamaParse OCR
        parser = _get_llama_parser()
        if parser is not None:
            try:
                # LlamaParse 需要文件路径，将 bytes 写入临时文件
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                    tmp.write(file_content)  # 后端 写入临时文件
                    tmp_path = tmp.name  # 后端 记录临时文件路径
                docs = parser.load_data(tmp_path)  # 后端 LlamaParse OCR 解析
                os.unlink(tmp_path)  # 后端 清理临时文件
                if docs:  # 后端 解析成功，合并所有页面
                    return "\n\n".join(doc.text for doc in docs if hasattr(doc, 'text'))
            except Exception as e:
                print(f"[警告] LlamaParse 解析 PDF 失败: {e}")

        return ""  # 后端 两种方式都失败，返回空

    # ========== LlamaParse 专属格式：DOCX / PPTX / 图片 / Excel / HTML ==========
    if ext in (
        '.docx', '.doc',  # Word 文档
        '.pptx', '.ppt',  # PowerPoint 演示文稿
        '.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif',  # 图片格式（OCR）
        '.xlsx', '.xls',  # Excel 电子表格
        '.html', '.htm',  # HTML 网页
    ):
        parser = _get_llama_parser()
        if parser is not None:
            try:
                # 写入临时文件供 LlamaParse 读取
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(file_content)  # 后端 写入临时文件
                    tmp_path = tmp.name
                docs = parser.load_data(tmp_path)  # 后端 LlamaParse 解析
                os.unlink(tmp_path)  # 后端 清理
                if docs:
                    return "\n\n".join(doc.text for doc in docs if hasattr(doc, 'text'))
            except Exception as e:
                print(f"[警告] LlamaParse 解析 {ext} 失败: {e}")

        return ""  # 后端 无 LlamaParse 或解析失败

    return ""  # 后端 不支持的文件格式


def is_format_supported(filename: str) -> bool:
    """后端 检查文件格式是否被当前配置支持（考虑了 LlamaParse 是否可用）"""
    ext = os.path.splitext(filename)[1].lower()
    basic_formats = {'.txt', '.md', '.csv', '.pdf'}  # 后端 始终支持的格式（pdfplumber）
    advanced_formats = {  # 后端 需要 LlamaParse 才能支持的格式
        '.docx', '.doc', '.pptx', '.ppt',
        '.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif',
        '.xlsx', '.xls', '.html', '.htm',
    }
    if ext in basic_formats:
        return True
    if ext in advanced_formats and settings.LLAMA_CLOUD_API_KEY:
        return True
    return False


def get_supported_extensions() -> list[str]:
    """后端 返回当前配置下支持的文件扩展名列表（用于前端 accept 属性）"""
    exts = ['.txt', '.pdf', '.md', '.csv']  # 后端 基础格式
    if settings.LLAMA_CLOUD_API_KEY:  # 后端 配置了 LlamaParse → 扩展更多格式
        exts += ['.docx', '.doc', '.pptx', '.ppt', '.png', '.jpg', '.jpeg',
                 '.tiff', '.bmp', '.gif', '.xlsx', '.xls', '.html', '.htm']
    return exts
