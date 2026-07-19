# Claude Gateway — UI 规范

## CSS 架构

按**职责**拆分，不按视觉组件拆。判断一个样式放哪看**生命周期**，不看视觉外观。

```
base.css        reset + :root 变量 + html/body + .screen
layout.css      持久结构:  header / sidebar / compose-bar / welcome / settings-panel / file-preview
controls.css    复用控件:  .btn-* / .icon-btn / .form-row / input / select / .preset-btn / .sys-actions
chat.css        消息相关:  .msg / code / pre / table / .thinking-fold / .download-card / .chat-image / .file-badges / .status-bar
overlay.css     临时浮层:  .confirm-* / .toast / .ctx-menu / .action-sheet / .image-overlay / .settings-overlay
scrollbar.css   自定义滚动条
```

组件 CSS 可被页面引用，页面 CSS 不能修改组件。

## 类名规范

- 全小写 + 连字符: `conv-item`、`file-preview`、`btn-small`
- 简单名，全局唯一，不用父子选择器嵌套
- 不用 BEM 双下划线/双横线
- 状态用独立类: `.hidden`、`.active`、`.collapsed`、`.editable`

## 变量

只通过 CSS 变量使用颜色和字体，禁止写死值：

```css
/* 可用变量 */
--bg-primary, --bg-surface, --bg-surface-2, --bg-input
--text-primary, --text-dim, --text-bright
--accent, --accent-hover, --accent-dim
--bubble-user, --bubble-assistant, --bubble-border
--thinking-bg, --thinking-border
--border, --danger
--radius, --radius-sm
--font, --font-mono
--safe-bottom
```

## 数值体系

当前使用的实际值，不设抽象 scale：

**间距 (padding/margin/gap)：** `2` `4` `5` `6` `8` `10` `12` `14` `16` `20` `24` `28` `32`

**字号：** `.68` `.72` `.75` `.78` `.82` `.85` `.88` `.9` `.93` `.95` `1.05` `1.1` `1.2` `1.4` `1.6` rem

**圆角：** `3` `4` `6` `8` `10` `16` `20` `24`

## !important

只在覆盖浏览器/第三方默认样式时允许（如 webkit scrollbar 伪元素）。其他情况禁止，改用选择器优先级解决。

## HTML 规范

### 禁止 inline onclick

全部走 JS `addEventListener`：

```html
<!-- ❌ -->
<button onclick="doSomething()">

<!-- ✅ -->
<button id="my-btn">
```

### 动态元素用 data-* + 事件委托

```javascript
// 在最近的静态祖先上委托
dom.filePreviewBar.addEventListener('click', e => {
    const btn = e.target.closest('.remove');
    if (!btn) return;
    const index = parseInt(btn.dataset.index);
    // ...
});
```

### 唯一例外：onerror

`<img onerror="window._gwImgError(this)">` 允许——JS 无法可靠监听动态 img 的加载失败。但只允许单个函数调用，禁止多语句。

### 文本必须有独立元素

```html
<!-- ❌ 裸文本 -->
<div class="chip">📎 filename.txt <span class="remove">✕</span></div>

<!-- ✅ 包裹 -->
<div class="chip">📎 <span class="chip-name">filename.txt</span> <span class="remove">✕</span></div>
```

凡是需要 CSS 截断、JS 操作、或独立样式的文本，必须有独立标签。

## 组件哲学

1. **一个模块一个职责** — 组件做 UI 组装，不做网络请求；render 做渲染，不存状态
2. **新增功能优先复用已有模块** — 搜索现有代码，能 import 就不要复制
3. **生命周期决定归属** — 一个元素看起来像浮层（如 sidebar），但如果一直存在于 DOM 中，放 `layout.css` 而非 `overlay.css`
