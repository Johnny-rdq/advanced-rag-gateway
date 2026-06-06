import os
import io
import datetime
from app.database.chroma_store import add_documents_to_db

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


def import_local_docs():
    """🌟 修复核心：扫描本地 docs 文件夹（TXT/PDF），自动切片向量化入库"""
    docs_dir = "docs"
    if not os.path.exists(docs_dir):
        os.makedirs(docs_dir, exist_ok=True)
        print(f"❌ 未找到 {docs_dir} 文件夹，已帮你新建！请往里塞入 TXT 或 PDF 文件后再次运行！")
        return

    all_chunks = []
    supported_files = []
    print(f"⏳ 开始扫描本地 docs 文件夹...")

    for filename in os.listdir(docs_dir):
        filepath = os.path.join(docs_dir, filename)
        if not os.path.isfile(filepath): continue

        text = ""
        # PDF 解析
        if filename.endswith(".pdf"):
            if pdfplumber:
                try:
                    with pdfplumber.open(filepath) as pdf:
                        for page in pdf.pages:
                            extracted_text = page.extract_text()
                            if extracted_text: text += extracted_text + "\n"
                    supported_files.append(filename)
                except Exception as e:
                    print(f"❌ 读取 PDF {filename} 失败: {e}")
            else:
                print(f"⚠️ 未安装 pdfplumber，跳过 PDF {filename}")
        # TXT 解析
        elif filename.endswith(".txt"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    text = f.read()
                supported_files.append(filename)
            except Exception as e:
                print(f"❌ 读取 TXT {filename} 失败: {e}")

        if text.strip():
            # 按照 400 字一段进行切片
            chunks = [text[i:i + 400] for i in range(0, len(text), 400) if text[i:i + 400].strip()]
            all_chunks.extend(chunks)
            print(f"📄 成功解析文档 [{filename}]，切分为 {len(chunks)} 个向量知识片段")

    if all_chunks:
        # 🌟 修复核心：调用 ChromaDB 的接口，把文件永久刻入硬盘！
        add_documents_to_db(all_chunks)
        print(
            f"✅ 大功告成！已成功将 {len(supported_files)} 个本地文档（共 {len(all_chunks)} 个片段）注入 RAG 知识库！你可以启动服务测试了。")
    else:
        print("⚠️ docs 文件夹为空，或者没有读取到合法的 TXT/PDF 文字，知识库注入失败。")


if __name__ == "__main__":
    import_local_docs()