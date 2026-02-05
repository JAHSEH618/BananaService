#!/bin/bash
# 测试纯文本生成 / Test text-only generation

echo "测试 1: 纯文本生成 / Test 1: Text-only generation"
curl -X POST "http://127.0.0.1:8000/generate" \
     -H "Content-Type: application/json" \
     -d '{
           "prompt": "一只穿着宇航服的香蕉 / A banana wearing a spacesuit"
         }'

echo -e "\n\n测试 2: 图片+文本生成 / Test 2: Image + Text generation"
echo "注意: 需要提供 base64 编码的图片 / Note: Requires base64 encoded image"

# 示例 base64 图片请求 / Example base64 image request
# 实际使用时替换 YOUR_BASE64_IMAGE_DATA
# curl -X POST "http://127.0.0.1:8000/generate" \
#      -H "Content-Type: application/json" \
#      -d '{
#            "prompt": "根据这张图片生成一个变体 / Generate a variant based on this image",
#            "image_base64": "data:image/jpeg;base64,YOUR_BASE64_IMAGE_DATA"
#          }'
