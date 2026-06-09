"""生成 Chrome 扩展图标

使用方法：
1. 安装 Pillow: pip install Pillow
2. 运行: python generate_icons.py

或者使用在线工具将 icon.svg 转换为 16x16、48x48、128x128 的 PNG
"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_icon(size, output_path):
    """创建 PaperLens 图标"""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 绘制圆角矩形背景
    margin = size // 8
    radius = size // 6
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=radius,
        fill=(37, 99, 235)  # #2563eb
    )

    # 绘制放大镜
    cx, cy = size // 2 - size // 16, size // 2 - size // 16
    r = size // 4
    line_width = max(2, size // 16)

    # 放大镜圆圈
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        outline='white',
        width=line_width
    )

    # 放大镜手柄
    handle_start = (cx + int(r * 0.7), cy + int(r * 0.7))
    handle_end = (cx + int(r * 1.4), cy + int(r * 1.4))
    draw.line([handle_start, handle_end], fill='white', width=line_width)

    # 绘制论文线条
    paper_x = size // 2 - size // 5
    paper_y = size // 2 - size // 4
    paper_w = size // 3
    paper_h = size // 2

    # 论文背景
    draw.rectangle(
        [paper_x, paper_y, paper_x + paper_w, paper_y + paper_h],
        fill='white',
        outline=(37, 99, 235)
    )

    # 论文内容线条
    line_y = paper_y + paper_h // 4
    for i in range(3):
        draw.line(
            [paper_x + paper_w // 4, line_y, paper_x + paper_w * 3 // 4, line_y],
            fill=(37, 99, 235),
            width=max(1, size // 32)
        )
        line_y += paper_h // 5

    img.save(output_path, 'PNG')
    print(f"Created: {output_path}")

if __name__ == '__main__':
    icons_dir = os.path.join(os.path.dirname(__file__), 'icons')

    # 生成三种尺寸的图标
    for size in [16, 48, 128]:
        output_path = os.path.join(icons_dir, f'icon{size}.png')
        create_icon(size, output_path)

    print("\n图标生成完成！")
    print("如果无法运行此脚本，请使用在线工具将 icon.svg 转换为：")
    print("  - icon16.png (16x16)")
    print("  - icon48.png (48x48)")
    print("  - icon128.png (128x128)")
