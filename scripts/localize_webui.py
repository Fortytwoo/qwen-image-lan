from pathlib import Path
import argparse
import hashlib
import json

parser=argparse.ArgumentParser()
parser.add_argument('--input',required=True)
parser.add_argument('--output',required=True)
parser.add_argument('--origin',required=True)
args=parser.parse_args()
target=Path(args.output)
html=Path(args.input).read_text(encoding='utf-8')
html=html.replace('custom_sigmas:[]','custom_sigmas:[1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0]',1)

labels = {
    'Native async image and video generation interface for the local `stable-diffusion.cpp` server.': '本地图片与视频生成界面',
    'Image Generation': '图片生成', 'Video Generation': '视频生成',
    'Settings': '设置', 'Refresh Server Info': '刷新服务信息', 'Refreshing...': '正在刷新…',
    'Show': '展开', 'Hide': '收起',
    'Input': '输入', 'Output': '输出', 'Prompt': '提示词', 'Negative Prompt': '负面提示词',
    'Describe the image you want to generate': '描述你想生成的图片，支持中文和英文',
    'Describe the motion, scene, and framing you want to generate': '描述视频动作、场景和构图',
    'What should be excluded?': '描述不希望出现在图片中的内容',
    'Width': '宽度', 'Height': '高度', 'Batch Count': '生成数量', 'Seed': '随机种子',
    'Sample': '采样', 'Scheduler': '调度器', 'Flow Shift': '流匹配偏移',
    'Method': '采样方法', 'Steps': '采样步数', 'Show extras': '展开高级选项', 'Hide extras': '收起高级选项',
    'Eta': '噪声系数 Eta', 'Shifted Timestep': '时间步偏移',
    'Guidance': '引导', 'CFG Scale': '提示词引导强度 CFG', 'Distilled Guidance': '蒸馏引导强度',
    'Image CFG': '图像引导强度 CFG', 'SLG Layers': 'SLG 跳过层', 'SLG Layer Start': 'SLG 起始位置',
    'SLG Layer End': 'SLG 结束位置', 'SLG Scale': 'SLG 引导强度',
    'Conditioning': '条件控制', 'CLIP Skip': 'CLIP 跳层', 'Strength': '重绘强度',
    'Control Strength': '控制图引导强度', 'VACE Strength': 'VACE 引导强度',
    'No LoRA': '未使用 LoRA', 'Add LoRA': '添加 LoRA', 'Multiplier': '权重倍率',
    'No LoRA entries were returned by capabilities.': '当前服务未提供可用的 LoRA。',
    'No LoRA overrides configured.': '尚未配置 LoRA。',
    'Image Inputs': '输入图片', 'No images': '未添加图片',
    'Init Image': '初始图片', 'Mask Image': '蒙版图片', 'Control Image': '控制图片',
    'Reference Images': '参考图片', 'Drop, paste, or browse an image to seed generation.': '拖入、粘贴或选择图片作为生成起点。',
    'One-channel mask image.': '单通道蒙版图片。', 'ControlNet-style guidance image.': '用于 ControlNet 引导的图片。',
    'Multiple reference images supported.': '支持添加多张参考图片。',
    'No files selected.': '尚未选择文件。', 'Remove': '移除',
    'VAE Tiling': 'VAE 分块', 'Enabled': '启用', 'Disabled': '已禁用',
    'Tile Width (px)': '分块宽度（像素）', 'Tile Height (px)': '分块高度（像素）',
    'Target Overlap': '重叠比例', 'Relative Width': '相对宽度', 'Relative Height': '相对高度',
    'Preview': '预览', 'Preview Mode': '预览方式', 'Interval (steps)': '预览间隔（步）',
    'Cache': '缓存', 'Cache Option': '缓存参数', 'Dynamic SCM Policy': '动态 SCM 策略',
    'SCM Mask': 'SCM 步数掩码', 'High Noise': '高噪声阶段', 'High Noise Pass': '高噪声采样',
    'Generate Image': '生成图片', 'Generate Images': '生成图片', 'Generate Video': '生成视频',
    'Generated output': '生成结果', 'Expanded image': '图片大图', 'Live preview': '实时预览',
    'Generated images will appear here once the current job finishes.': '生成完成后，图片将显示在这里。',
    'Generated video or animated WebP output will appear here once the current job finishes.': '生成完成后，视频或 WebP 动画将显示在这里。',
    'Status': '状态', 'Queue': '排队数量', 'Created': '创建时间', 'Elapsed': '耗时',
    'No job': '暂无任务', 'Idle': '空闲', 'Download': '下载', 'Cancel': '取消', 'Close': '关闭',
    'Image generation completed.': '图片生成完成。', 'Video generation completed.': '视频生成完成。',
    'Generation failed.': '生成失败。', 'Job cancelled.': '任务已取消。',
    'prompt is required': '请先填写提示词', 'Pasted image into init_image.': '已粘贴图片作为初始图片。',
    'Base URL': '服务地址', 'Leave blank to use same origin': '留空则使用当前服务地址',
    'Job Poll Interval (ms)': '任务刷新间隔（毫秒）', 'Queue Limit': '队列上限',
    'No model info': '暂无模型信息', 'Mode': '模式', 'Output Format': '输出格式',
    'Output Formats (': '输出格式（', 'Output Compression': '输出压缩质量',
    'Current model only supports image generation.': '当前模型仅支持图片生成。',
    'Current model only supports video generation.': '当前模型仅支持视频生成。',
    'Frames': '帧数', 'Video Frames': '视频帧数', 'FPS': '帧率 FPS', 'MoE Boundary': 'MoE 阶段边界',
    'Start Frame': '起始帧', 'End Frame': '结束帧', 'Control Frames': '控制帧',
    'Optional first frame or seed image for the sequence.': '可选，用作视频的第一帧或起始图片。',
    'Optional end frame for interpolation or FLF2V-style runs.': '可选，用作插帧或首尾帧生成的结束帧。',
    'Reference Images (MiniMax-H3 Ref2VA only)': '参考图片（仅用于 MiniMax-H3 Ref2VA）',
    'Only MiniMax-H3 Ref2VA uses these images; other video models ignore them. Cannot be combined with an initial or end frame.': '仅 MiniMax-H3 Ref2VA 使用这些图片；其他视频模型会忽略。不能与起始帧或结束帧同时使用。',
    'Upload ordered conditioning frames. The server preserves the array order.': '按顺序上传控制帧，服务端会保留此顺序。',
    'Video reference images cannot be combined with an initial or end frame. Clear the reference images or both keyframes before generating.': '视频参考图片不能与起始帧或结束帧同时使用。请先清除参考图片或首尾关键帧再生成。',
    'Browser playback for AVI depends on codec support. Download the file if the preview cannot play.': 'AVI 播放取决于浏览器的编解码支持；无法预览时可下载文件查看。',
    'blank = auto': '留空则自动选择', 'blank = default': '留空则使用默认值',
    'blank = follow text cfg': '留空则跟随提示词 CFG',
}

start = html.index('<script type="module" crossorigin>')
end = html.index('</script>', start)
module = html[start:end]
counts = {}
for english, chinese in labels.items():
    for source in (english, f' {english} '):
        literal = json.dumps(source, ensure_ascii=False)
        count = module.count(literal)
        if count:
            replacement = json.dumps(chinese if source == english else f' {chinese} ', ensure_ascii=False)
            module = module.replace(literal, replacement)
            counts[english] = counts.get(english, 0) + count

# Keep generated values and transport identifiers unchanged; only localize the rendered summary.
dynamic = {
    '`queue ${ts.value}`': '`队列容量 ${ts.value}`',
    '`${m.control_frames.length} frames`': '`${m.control_frames.length} 帧`',
    '`${m.lora.length} configured`': '`已配置 ${m.lora.length} 项`',
    '`${m.ref_images.length} refs`': '`${m.ref_images.length} 张参考图`',
    ' \u00b7 overlap ': ' \u00b7 重叠 ',
    ' \\xB7 overlap ': ' \\xB7 重叠 ',
    '`Output ${re+1}`': '`输出 ${re+1}`',
    '`failed to read ${e.name}`': '`无法读取文件 ${e.name}`',
    '`cfg ${o} \\xB7 distilled ${H}`': '`CFG ${o} \\xB7 蒸馏 ${H}`',
    '`clip_skip ${p} \\xB7 img ${o} \\xB7 control ${H}`': '`CLIP 跳层 ${p} \\xB7 重绘 ${o} \\xB7 控制 ${H}`',
    '`clip_skip ${p} \\xB7 strength ${o} \\xB7 vace ${is(m.vace_strength)}`': '`CLIP 跳层 ${p} \\xB7 重绘 ${o} \\xB7 VACE ${is(m.vace_strength)}`',
    '"service online"': '"服务在线"', '"service unavailable"': '"服务不可用"',
    '"flow auto"': '"自动流偏移"', '`flow ${p.flow_shift}`': '`流偏移 ${p.flow_shift}`',
    '" steps"': '" 步"', '"Pass "': '"采样阶段 "',
}
for source, replacement in dynamic.items():
    module = module.replace(source, replacement)
html = html[:start] + module + html[end:]
html = html.replace('<html lang="en">', '<html lang="zh-CN">', 1)
html = html.replace('<title>stable-diffusion.cpp WebUI</title>', '<title>Qwen-Image 本地生图</title>', 1)

summary_labels = {
    'idle': '空闲', 'queued': '排队中', 'generating': '正在生成', 'completed': '已完成',
    'failed': '失败', 'cancelled': '已取消', 'offline': '离线',
    'default': '默认', 'disabled': '已禁用', 'enabled': '已启用',
    'none': '无', 'Off': '关闭', 'On': '开启', 'image': '图片', 'video': '视频',
}
summary_script = '''
<!-- qwen-local-zh: Render status and option labels without changing API values. -->
<script>
(() => {
  const labels = SUMMARY_LABELS;
  const skipped = 'script,style,textarea,input,[contenteditable="true"]';
  function localizeText(node) {
    if (!node.parentElement || node.parentElement.closest(skipped)) return;
    const original = node.nodeValue;
    const value = original.trim();
    if (Object.prototype.hasOwnProperty.call(labels, value)) {
      node.nodeValue = original.replace(value, labels[value]);
    } else if (value === '输出格式（image)' || value === '输出格式（video)') {
      node.nodeValue = original.replace(value, value === '输出格式（image)' ? '输出格式（图片）' : '输出格式（视频）');
    } else if (value === 'image)' || value === 'video)') {
      node.nodeValue = original.replace(value, value === 'image)' ? '图片）' : '视频）');
    } else if (value === ')' && node.parentElement.textContent.startsWith('输出格式（')) {
      node.nodeValue = original.replace(value, '）');
    }
  }
  function visit(root) {
    if (root.nodeType === Node.TEXT_NODE) { localizeText(root); return; }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) localizeText(walker.currentNode);
  }
  const observer = new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') localizeText(record.target);
      else for (const node of record.addedNodes) visit(node);
    }
  });
  observer.observe(document.body, {subtree:true, childList:true, characterData:true});
  visit(document.body);
})();
</script>
<style>body{font-family:"Microsoft YaHei UI","Microsoft YaHei","PingFang SC",system-ui,sans-serif}</style>
'''.replace('SUMMARY_LABELS', json.dumps(summary_labels, ensure_ascii=False))
html = html.replace('</body>', summary_script + '</body>', 1)
sigmas = 'custom_sigmas:[1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0]'
assert html.count(sigmas) == 1, 'Turbo schedule must be preserved.'
assert len(counts) >= 100, 'Unexpected native UI version; translation coverage too low.'
redirect='<script>if(location.port==="1235"&&(location.hostname==="127.0.0.1"||location.hostname==="localhost")){location.replace('+json.dumps(args.origin+'/')+');}</script>'
html=html.replace('<head>','<head>'+redirect,1)
html=html.replace('支持添加多张参考图片。','改图使用一张参考图片，单张不超过 8 MB；也可点击顶部“改图”。')
start=html.index('const cu=[')
end=html.index('],du=[',start)
html=html[:start]+'const cu=[]'+html[end+1:]
target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(html,encoding='utf-8')
print(json.dumps({'language':'zh-CN','translation_keys':len(counts),'turbo_sigmas_preserved':True,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))
