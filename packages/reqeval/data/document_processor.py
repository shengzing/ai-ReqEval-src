"""
文档处理模块 - 支持PDF, Word, Excel, TXT等格式
"""
from pathlib import Path
from typing import Optional, Dict, Any
import io

try:
    from pypdf import PdfReader
except ImportError:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None

try:
    import openpyxl
    import pandas as pd
except ImportError:
    openpyxl = None
    pd = None


class DocumentProcessor:
    """文档处理器"""

    @staticmethod
    def process_file(file) -> str:
        """
        处理上传的文件，返回文本内容

        Args:
            file: 上传文件对象、file-like object 或文件路径

        Returns:
            提取的文本内容
        """
        # 获取文件名
        if hasattr(file, 'name'):
            filename = file.name
        else:
            filename = str(file)

        file_ext = Path(filename).suffix.lower()

        # 根据文件类型选择处理方法
        if file_ext == '.pdf':
            return DocumentProcessor.parse_pdf(file)
        elif file_ext in ['.docx', '.doc']:
            return DocumentProcessor.parse_word(file)
        elif file_ext in ['.xlsx', '.xls']:
            return DocumentProcessor.parse_excel(file)
        elif file_ext == '.txt':
            return DocumentProcessor.parse_text(file)
        elif file_ext in ['.md', '.markdown']:
            return DocumentProcessor.parse_text(file)
        else:
            raise ValueError(f"不支持的文件格式: {file_ext}")

    @staticmethod
    def parse_pdf(file) -> str:
        """解析PDF文件"""
        if PdfReader is None:
            raise ImportError("请安装PyPDF2: pip install PyPDF2")

        try:
            # 如果是文件路径
            if isinstance(file, (str, Path)):
                with open(file, 'rb') as f:
                    pdf_reader = PdfReader(f)
                    text = ""
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n"
                    return text
            # 如果是文件对象
            else:
                pdf_reader = PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
                return text
        except Exception as e:
            raise ValueError(f"PDF解析失败: {str(e)}")

    @staticmethod
    def parse_word(file) -> str:
        """解析Word文件"""
        if Document is None:
            raise ImportError("请安装python-docx: pip install python-docx")

        try:
            # 如果是文件路径
            if isinstance(file, (str, Path)):
                doc = Document(file)
            else:
                # 如果是文件对象
                doc = Document(file)

            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"

            # 提取表格内容
            for table in doc.tables:
                for row in table.rows:
                    row_text = "\t".join([cell.text for cell in row.cells])
                    text += row_text + "\n"

            return text
        except Exception as e:
            raise ValueError(f"Word文档解析失败: {str(e)}")

    @staticmethod
    def parse_excel(file) -> str:
        """解析Excel文件"""
        if pd is None or openpyxl is None:
            raise ImportError("请安装openpyxl和pandas: pip install openpyxl pandas")

        try:
            # 读取所有sheet
            if isinstance(file, (str, Path)):
                excel_file = pd.ExcelFile(file)
            else:
                excel_file = pd.ExcelFile(file)

            text = ""
            for sheet_name in excel_file.sheet_names:
                df = pd.read_excel(excel_file, sheet_name=sheet_name)
                text += f"\n=== Sheet: {sheet_name} ===\n"
                text += df.to_string(index=False) + "\n"

            return text
        except Exception as e:
            raise ValueError(f"Excel文件解析失败: {str(e)}")

    @staticmethod
    def parse_text(file) -> str:
        """解析纯文本文件"""
        try:
            if isinstance(file, (str, Path)):
                with open(file, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                # 上传文件对象
                return file.read().decode('utf-8')
        except UnicodeDecodeError:
            # 尝试其他编码
            try:
                if isinstance(file, (str, Path)):
                    with open(file, 'r', encoding='gbk') as f:
                        return f.read()
                else:
                    file.seek(0)
                    return file.read().decode('gbk')
            except Exception as e:
                raise ValueError(f"文本文件解析失败: {str(e)}")

    @staticmethod
    def extract_structured_data(
        text: str,
        schema: Dict[str, Any],
        llm_client=None
    ) -> Dict[str, Any]:
        """
        使用LLM从文本中提取结构化数据

        Args:
            text: 文档文本
            schema: 期望的数据结构定义
            llm_client: LLM客户端（可选）

        Returns:
            提取的结构化数据
        """
        if llm_client is None:
            # 如果没有LLM，返回空字典
            return {}

        # 构建提示词
        prompt = f"""
请从以下文档中提取信息，并按照指定的结构返回JSON格式的数据。

数据结构要求:
{schema}

文档内容:
{text[:5000]}  # 限制长度

请直接返回JSON格式的数据，不要有其他说明文字。
"""

        try:
            response = llm_client.generate(prompt)
            import json
            return json.loads(response)
        except Exception as e:
            print(f"结构化数据提取失败: {e}")
            return {}


# 文档摘要生成
def generate_document_summary(text: str, max_length: int = 500) -> str:
    """
    生成文档摘要

    Args:
        text: 文档文本
        max_length: 摘要最大长度

    Returns:
        文档摘要
    """
    # 简单的截断策略
    if len(text) <= max_length:
        return text

    # 尝试在句号处截断
    truncated = text[:max_length]
    last_period = truncated.rfind('。')
    if last_period > max_length * 0.7:
        return truncated[:last_period + 1] + "..."
    else:
        return truncated + "..."
