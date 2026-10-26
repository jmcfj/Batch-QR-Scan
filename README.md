# Batch QR Scan · 批量扫码

Windows 中文桌面软件，批量识别图片和 PDF 页面中的二维码、条形码。所有扫描在本机完成，无需上传文件。

## 使用

双击根目录的 `启动软件.bat`，或直接运行 `dist/BatchQRScan/BatchQRScan.exe`。
打包后的 `BatchQRScan` 整个目录需要保留，不能只复制 EXE。

1. 添加多个文件，或选择文件夹递归导入。重复路径自动跳过。
2. 也可使用 Win + Shift + S 截图，再点「粘贴截图」。
3. 点「开始扫描」。每次开始会重建结果；每页可识别多个码，保留页码与位置。
4. 可停止扫描，已完成的记录保留。停止需要等待当前页解码完成。
5. 搜索文件名、内容、码类型或状态；勾选「仅已识别」过滤空白和失败记录。
6. 选中结果查看完整文本与路径，支持多选复制或 Ctrl+C。
7. 导出全部结果为 UTF-8 BOM CSV 或 JSON；包含未发现码和失败记录，不受筛选影响。

## 网址二维码：查看网页内容

默认勾选「扫描后打开首个网页」：扫描结束后，在系统默认浏览器中打开首个识别到的 HTTP/HTTPS 网址，展示网页实际内容（含网页自身的跳转）。批量扫描只自动打开一个网页，其他网址可选中后点「打开网页」、双击对应行或按 Enter 打开。取消勾选可关闭自动打开；停止扫描时不会自动打开。

支持 `http://`、`https://` 和 `www.` 开头的网址。普通文本仍显示原文。网页需要联网；需登录的页面会在浏览器中要求登录。微信专属小程序或私有协议不能直接当作普通网页打开。

图片格式：PNG、JPEG、BMP、WebP、TIFF、GIF；TIFF/GIF 会逐帧扫描。
码类型由 ZXing-C++ 提供，包括 QR Code、Code 128、Code 39、EAN、UPC、Data Matrix、PDF417 等。
同一内容出现在多个页面或多个位置时分别保留，便于溯源。

## 限制

- 密码保护、损坏或不可读文件显示失败信息，继续处理后续文件。
- PDF 以约 216 DPI 渲染，单边最高 6000 像素；极小、模糊或遮挡的码可能无法识别。
- 当前版本面向本地图片和 PDF，不包含网页 URL 抓取或摄像头扫描。
- CSV 对可能触发表格公式的内容添加前置单引号；JSON 保留原始文本。

## 开发与检查

Python 3.12，Windows 10/11。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe app.py
.\.venv\Scripts\python.exe -m pytest -q
.\build.ps1
```

自动检查覆盖：同图多码、二维码/Code128、多页 TIFF、多页 PDF、空白页、文件错误、取消、导出保护、桌面导入/后台扫描/筛选/复制。

## 依赖

- [ZXing-C++ Python](https://pypi.org/project/zxing-cpp/)：码识别。
- [pypdfium2](https://pypdfium2.readthedocs.io/en/stable/python_api.html)：PDF 页面渲染。
- Pillow：图片读取；Tkinter：桌面界面；PyInstaller：Windows 打包。

功能检查通过后分阶段提交并推送到关联仓库。
