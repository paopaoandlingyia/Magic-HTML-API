from fastapi import FastAPI, HTTPException
import httpx
from magic_html import GeneralExtractor
from typing import Optional, Literal
from markdownify import markdownify as md
from bs4 import BeautifulSoup
import re
import chardet

app = FastAPI()
extractor = GeneralExtractor()

async def fetch_url(url: str) -> str:
    # 模拟常见浏览器请求头，提升兼容性（尤其是公众号等站点）
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
    }

    # 公众号等域名适配 Referer
    if any(domain in url.lower() for domain in ["mp.weixin.qq.com", "weixin.qq.com"]):
        headers["Referer"] = "https://mp.weixin.qq.com/"

    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=15.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            
            # 处理响应编码
            content_type = response.headers.get('content-type', '').lower()
            if 'charset=' in content_type:
                try:
                    charset = content_type.split('charset=')[-1].split(';')[0]
                    return response.content.decode(charset)
                except:
                    pass
            
            try:
                return response.content.decode('utf-8')
            except UnicodeDecodeError:
                content = response.content
                detected = chardet.detect(content)
                encoding = detected['encoding']
                
                if encoding and encoding.lower() in ['gb2312', 'gbk']:
                    encoding = 'gb18030'
                
                return content.decode(encoding or 'utf-8')
            
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error fetching URL: {str(e)}")

def convert_content(html: str, output_format: str) -> str:
    """
    将HTML内容转换为指定格式
    
    Args:
        html: HTML内容
        output_format: 输出格式 ("html", "markdown", "text")
        
    Returns:
        转换后的内容
    """
    if not isinstance(html, str):
        html = str(html)
        
    if output_format == "html":
        return html
    elif output_format == "markdown":
        return md(html, 
                 heading_style="ATX",  # 使用 # 风格的标题
                 bullets="*",  # 统一使用 * 作为列表符号
                 autolinks=True,  # 启用自动链接
                 code_language="",  # 保持代码块的语言标记
                 escape_asterisks=False,  # 不转义文本中的星号
                 escape_underscores=False,  # 不转义下划线
                 newline_style="SPACES")  # 使用标准markdown换行方式
    elif output_format == "text":
        soup = BeautifulSoup(html, 'html.parser')
        return soup.get_text(separator='\n', strip=True)
    else:
        return html

def extract_html_content(data: dict) -> str:
    """
    从magic_html返回的数据中提取HTML内容
    
    Args:
        data: magic_html返回的数据
        
    Returns:
        HTML内容
    """
    if isinstance(data, dict):
        return data.get('html', '')
    return ''

def detect_html_type(html: str, url: str) -> str:
    """
    自动检测HTML类型
    
    Args:
        html: HTML内容
        url: 页面URL
        
    Returns:
        检测到的类型 ("article", "forum", "weixin", "jina")
    """
    # 检查URL特征
    url_lower = url.lower()
    if any(domain in url_lower for domain in ['mp.weixin.qq.com', 'weixin.qq.com']):
        return 'weixin'
    elif 'zhihu.com' in url_lower:
        return 'jina'
    
    # 检查HTML特征
    soup = BeautifulSoup(html, 'html.parser')
    
    # 论坛特征检测
    forum_indicators = [
        'forum', 'topic', 'thread', 'post', 'reply', 'comment', 'discuss',
        '论坛', '帖子', '回复', '评论', '讨论'
    ]
    
    # 检查类名和ID
    classes_and_ids = []
    for element in soup.find_all(class_=True):
        classes_and_ids.extend(element.get('class', []))
    for element in soup.find_all(id=True):
        classes_and_ids.append(element.get('id', ''))
    
    classes_and_ids = ' '.join(classes_and_ids).lower()
    
    if any(indicator in classes_and_ids for indicator in forum_indicators):
        return 'forum'
    
    # 默认为文章类型
    return 'article'

# 添加jina.ai提取函数
async def fetch_from_jina(url: str) -> str:
    """
    使用jina.ai服务提取内容,最多等待15秒
    
    Args:
        url: 目标网页URL
        
    Returns:
        提取的内容
    """
    jina_url = f"https://r.jina.ai/{url}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(jina_url)
        response.raise_for_status()
        return response.text

def convert_markdown(markdown: str, output_format: str) -> str:
    """
    将markdown内容转换为指定格式
    
    Args:
        markdown: Markdown内容
        output_format: 输出格式 ("html", "markdown", "text")
        
    Returns:
        转换后的内容
    """
    if output_format == "markdown":
        return markdown
    elif output_format == "text":
        # 移除markdown标记
        text = re.sub(r'!\[.*?\]\(.*?\)', '[图片]', markdown)  # 替换图片
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # 替换链接
        text = re.sub(r'[#*`]', '', text)  # 移除特殊字符
        return text.strip()
    elif output_format == "html":
        # 这里可以使用markdown到html的转换库，比如markdown2或mistune
        # 暂时返回原始markdown
        return markdown
    return markdown

@app.get("/api/extract")
async def extract_content(
    url: str, 
    output_format: Optional[Literal["html", "markdown", "text"]] = "text"
):
    """
    从URL提取内容
    
    Args:
        url: 目标网页URL
        output_format: 输出格式 ("html", "markdown", "text")，默认为text
    
    Returns:
        JSON格式的提取内容
    """
    try:
        # 检测是否是知乎页面
        if 'zhihu.com' in url:
            markdown_content = await fetch_from_jina(url)
            content = convert_markdown(markdown_content, output_format)
            return {
                "url": url,
                "content": content,
                "format": output_format,
                "type": "jina",
                "success": True
            }
            
        # 尝试使用原有逻辑
        try:
            html = await fetch_url(url)
            html_type = detect_html_type(html, url)
            extracted_data = extractor.extract(html, base_url=url, html_type=html_type)
            html_content = extract_html_content(extracted_data)
            
            # 检查提取结果是否为空
            if not html_content or html_content.isspace():
                # 如果为空，尝试使用jina.ai
                markdown_content = await fetch_from_jina(url)
                content = convert_markdown(markdown_content, output_format)
                return {
                    "url": url,
                    "content": content,
                    "format": output_format,
                    "type": "jina",
                    "success": True
                }
            
            # 使用原有结果
            converted_content = convert_content(html_content, output_format)
            return {
                "url": url,
                "content": converted_content,
                "format": output_format,
                "type": html_type,
                "success": True
            }
            
        except Exception as e:
            # 如果原有逻辑失败，尝试使用jina.ai
            markdown_content = await fetch_from_jina(url)
            content = convert_markdown(markdown_content, output_format)
            return {
                "url": url,
                "content": content,
                "format": output_format,
                "type": "jina",
                "success": True
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 
