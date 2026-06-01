/** 移除 HTML 中的 <!-- ... --> 注释（不处理 script/style 内字符串外的复杂嵌套） */
export function stripHtmlComments(html) {
  return html.replace(/<!--[\s\S]*?-->/g, '')
}
