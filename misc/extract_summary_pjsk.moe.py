# deepseek

import os
import re
import glob

from bs4 import BeautifulSoup


def extract_event_info(html_file_path):
    """从HTML文件中提取活动信息"""
    with open(html_file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, 'html.parser')

    # 提取活动ID - 从多个可能的位置查找
    event_id = None
    # 方法1: 从包含"events/"的链接中提取
    links = soup.find_all('a', href=True)
    for link in links:
        href = link['href']
        # 查找类似"events/190"或"/events/190"的链接
        match = re.search(r'(?:/|^)events/(\d+)', href)  # type: ignore
        if match:
            event_id = match.group(1)
            break

        # 方法2: 从包含"eventstory/"的链接中提取
        match = re.search(r'(?:/|^)eventstory/(\d+)', href)  # type: ignore
        if match:
            event_id = match.group(1)
            break

    # 如果还没找到，尝试从当前页面的URL中提取
    if not event_id and 'eventstory/' in html_file_path:
        match = re.search(r'eventstory/(\d+)', html_file_path)
        if match:
            event_id = match.group(1)

    # 提取活动标题
    chinese_title = ""
    japanese_title = ""

    h1_tag = soup.find('h1', class_=re.compile('text-.*'))
    if h1_tag:
        chinese_title = h1_tag.get_text(strip=True)

    # 日文标题通常在中文标题下面的<p>标签中
    if h1_tag:
        next_p = h1_tag.find_next('p', class_=re.compile('text-.*'))
        if next_p:
            japanese_title = next_p.get_text(strip=True)

    # 提取背景提要
    background = ""
    # 查找包含"背景提要"的h3标签
    h3_tags = soup.find_all('h3')
    for h3 in h3_tags:
        if '背景提要' in h3.get_text():
            next_p = h3.find_next('p')
            if next_p:
                background = next_p.get_text(strip=True)
                break

    # 提取活动概要
    summary = ""
    # 查找包含"活动概要"的h2标签
    h2_tags = soup.find_all('h2')
    for h2 in h2_tags:
        if '活动概要' in h2.get_text():
            # 概要通常在h2后面的div或p标签中
            next_div = h2.find_next('div', class_=re.compile('prose.*'))
            if next_div:
                summary = next_div.get_text(strip=True)
                break

    # 提取章节列表
    chapters = []
    # 查找所有包含章节的<a>标签
    chapter_links = soup.find_all('a', href=re.compile(r'eventstory/\d+/\d+/'))
    for link in chapter_links:
        # 提取章节编号
        href = link['href']
        chapter_match = re.search(r'eventstory/\d+/(\d+)/', href)  # type: ignore
        chapter_num = chapter_match.group(1) if chapter_match else "0"

        # 提取章节标题
        title = ""
        title_tag = link.find('h3')
        if title_tag:
            title = title_tag.get_text(strip=True)

        # 提取章节描述
        description = ""
        desc_tag = link.find('p', class_=re.compile('text-sm.*'))
        if desc_tag:
            description = desc_tag.get_text(strip=True)

        # 清理描述文本，去除多余的空白
        description = ' '.join(description.split())

        chapters.append(
            {'number': chapter_num, 'title': title, 'description': description}
        )

    # 如果没有找到章节链接，尝试另一种查找方式
    if not chapters:
        # 查找所有包含章节编号的div
        chapter_divs = soup.find_all(
            'div',
            class_=lambda x: x and 'absolute' in x and 'top-1' in x and 'left-1' in x,  # type: ignore
        )
        for div in chapter_divs:
            if '#' in div.get_text():
                chapter_num = div.get_text(strip=True).replace('#', '')

                # 查找同一父容器中的标题和描述
                parent_div = div.find_parent('div', class_=re.compile('bg-white.*'))
                if parent_div:
                    title_tag = parent_div.find('h3')
                    title = title_tag.get_text(strip=True) if title_tag else ""

                    desc_tag = parent_div.find('p', class_=re.compile('text-sm.*'))
                    description = desc_tag.get_text(strip=True) if desc_tag else ""
                    description = ' '.join(description.split())

                    chapters.append(
                        {
                            'number': chapter_num,
                            'title': title,
                            'description': description,
                        }
                    )

    # 按章节编号排序
    chapters.sort(key=lambda x: int(x['number']))

    return {
        'event_id': event_id,
        'chinese_title': chinese_title,
        'japanese_title': japanese_title,
        'background': background,
        'summary': summary,
        'chapters': chapters,
    }


def generate_txt_content(event_info):
    """生成TXT文件内容"""
    content = f"活动标题: {event_info['chinese_title']}\n"
    content += f"日文标题: {event_info['japanese_title']}\n"
    content += f"活动ID: #{event_info['event_id']}\n"
    content += "=" * 50 + "\n\n"

    if event_info['background']:
        content += "📋 背景提要\n"
        content += f"{event_info['background']}\n\n"

    if event_info['summary']:
        content += "📝 活动概要\n"
        content += f"{event_info['summary']}\n\n"

    content += "=" * 50 + "\n\n"

    if event_info['chapters']:
        content += "📖 章节列表\n\n"
        for chapter in event_info['chapters']:
            content += f"第{chapter['number']}章: {chapter['title']}\n"
            content += f"{chapter['description']}\n"
            content += "-" * 30 + "\n\n"

    return content


def process_html_files(input_folder, output_folder):
    """处理HTML文件并生成TXT文件"""
    # 确保输出文件夹存在
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # 查找所有HTML文件
    html_files = glob.glob(os.path.join(input_folder, "*.html"))

    for html_file in html_files:
        print(f"处理文件: {html_file}")

        try:
            # 提取信息
            event_info = extract_event_info(html_file)

            if not event_info['event_id']:
                print(f"  警告: 无法从 {html_file} 中提取活动ID，跳过")
                continue

            # 生成TXT文件名
            # 清理标题中的非法文件名字符
            safe_title = re.sub(r'[<>:"/\\|?*]', '', event_info['chinese_title'])
            if not safe_title or safe_title.isspace():
                safe_title = f"event_{event_info['event_id']}"

            txt_filename = f"event_{event_info['event_id']}_{safe_title}.txt"
            txt_path = os.path.join(output_folder, txt_filename)

            # 生成内容并保存
            txt_content = generate_txt_content(event_info)

            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(txt_content)

            print(f"  已生成: {txt_path}")

        except Exception as e:
            print(f"  处理 {html_file} 时出错: {str(e)}")


def main():
    # 设置输入和输出文件夹
    input_folder = "html_pages"
    output_folder = "txt_output"

    # 处理所有HTML文件
    process_html_files(input_folder, output_folder)

    print("\n处理完成！")


if __name__ == "__main__":
    main()
