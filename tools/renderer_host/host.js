// 渲染器开发宿主：实现规范第 04 章中宿主一侧的要求（仅供本机开发调试）
'use strict'

const PROTOCOL = 'mentorbit.renderer/0.1'
const MAX_MESSAGE_BYTES = 256 * 1024
const MAX_PER_SECOND = 50
const THEMES = {
  light: { background: '#ffffff', foreground: '#1a1a1a', muted: '#666666', accent: '#2f6fdd', border: '#dddddd', fontFamily: 'system-ui, sans-serif', fontSizeBase: '15px' },
  dark: { background: '#202020', foreground: '#eeeeee', muted: '#999999', accent: '#7aa5ff', border: '#3a3a3a', fontFamily: 'system-ui, sans-serif', fontSizeBase: '15px' },
}

const params = new URLSearchParams(location.search)
const $ = id => document.getElementById(id)
const hostLog = []
window.__hostLog = hostLog // 便于自动化检查读取，宿主本身不依赖它

let manifest, renderer, objectType, envelope, iframe
let colorScheme = 'light'
let initialized = false
let initTimer
let nextId = 1
let windowStart = 0
let windowCount = 0
const viewState = new Map()

function log(direction, payload) {
  const entry = { t: Math.round(performance.now()), direction, payload }
  hostLog.push(entry)
  $('log').textContent += `${direction} ${JSON.stringify(payload)}\n`
  $('log').scrollTop = $('log').scrollHeight
}

function newObjectId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(13)), b => b.toString(16).padStart(2, '0')).join('')
}

function grants() {
  return $('grantStorage').checked && manifest.permissions?.some(p => p.id === 'storage.plugin') ? ['storage.plugin'] : []
}

function theme() {
  return { colorScheme, tokens: THEMES[colorScheme] }
}

function post(message) {
  const full = { jsonrpc: '2.0', ...message }
  log('→', full)
  // 渲染器是不透明源，只能以 '*' 为目标；安全性由只接受该 iframe 的 contentWindow 保证
  iframe.contentWindow.postMessage(full, '*')
}

function reply(id, result) { post({ id, result }) }
function fail(id, reason, code) { post({ id, error: { code, message: reason, data: { reason } } }) }

function showFallback(reason) {
  $('fallback').hidden = false
  $('fallback').textContent = `已改为展示 fallbackText（${reason}）：${envelope.fallbackText}`
  iframe?.remove()
}

function mount() {
  $('stage').replaceChildren()
  $('fallback').hidden = true
  $('suggestions').replaceChildren()
  initialized = false
  iframe = document.createElement('iframe')
  iframe.setAttribute('sandbox', 'allow-scripts') // 规范 4.2：只允许脚本
  iframe.setAttribute('allow', '') // 不授予任何 Permissions Policy 能力
  iframe.setAttribute('referrerpolicy', 'no-referrer')
  iframe.style.height = `${renderer.minHeight || 160}px`
  iframe.src = `/plugin/${renderer.entry}`
  let loads = 0
  iframe.addEventListener('load', () => {
    // 规范 4.2：首次加载之后再次加载，说明渲染器让 iframe 发生了跳转，必须卸载
    if (++loads > 1) showFallback('渲染器发生了页面跳转，已卸载')
  })
  $('stage').append(iframe)
  clearTimeout(initTimer)
  initTimer = setTimeout(() => { if (!initialized) showFallback('5 秒内未完成初始化') }, 5000)
}

// 规范 4.3：宿主必须校验每条消息的结构（与 renderer-messages.schema.json 中各方法的 Params 定义一致）
const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v)
const onlyKeys = (p, keys) => Object.keys(p).every(k => keys.includes(k))
const isKey = k => typeof k === 'string' && k.length >= 1 && k.length <= 64
const PARAM_RULES = {
  'ui/ready': p => onlyKeys(p, ['protocol']) && p.protocol === PROTOCOL,
  'ui/resize': p => onlyKeys(p, ['height']) && Number.isInteger(p.height) && p.height >= 0 && p.height <= 10000,
  'ui/suggestPrompt': p => onlyKeys(p, ['text']) && typeof p.text === 'string' && p.text.length >= 1 && p.text.length <= 500,
  'ui/openLink': p => onlyKeys(p, ['url']) && typeof p.url === 'string' && p.url.length <= 2048 && /^https:\/\/\S+$/.test(p.url),
  'state/get': p => onlyKeys(p, ['key']) && isKey(p.key),
  // 规范 4.5：单个值不超过 16 KiB
  'state/set': p => onlyKeys(p, ['key', 'value']) && isKey(p.key) && 'value' in p
    && new Blob([JSON.stringify(p.value)]).size <= 16 * 1024,
}

function handle(message) {
  const { id, method, params: raw } = message
  const p = raw === undefined ? {} : raw
  if (method !== undefined && PARAM_RULES[method] && !(isObj(p) && PARAM_RULES[method](p))) {
    if (id !== undefined) return fail(id, 'invalid_params', -32602)
    return log('!', `丢弃参数不合规的通知：${method}`)
  }
  if (method === undefined) { // 渲染器对宿主请求的响应
    if (message.error) return log('!', `渲染器返回错误：${message.error.message}`)
    if (id === 'init') {
      initialized = true
      clearTimeout(initTimer)
      log('·', '初始化完成')
    }
    return
  }
  switch (method) {
    case 'ui/ready':
      if (p?.protocol !== PROTOCOL) return log('!', `协议不匹配：${p?.protocol}`)
      return post({ id: 'init', method: 'render/init', params: {
        protocol: PROTOCOL, rendererId: `${manifest.id}/${renderer.id}`, object: envelope,
        locale: manifest.defaultLocale, theme: theme(), grants: grants(),
      } })
    case 'ui/resize': {
      const min = renderer.minHeight || 40
      const max = Math.min(renderer.maxHeight || 4000, 4000)
      const height = Math.max(min, Math.min(max, Number(p?.height) || min))
      iframe.style.height = `${height}px`
      return
    }
    case 'ui/suggestPrompt': {
      // 规范 4.5：只展示为建议，由学习者确认后才发送，宿主不得自动发送
      const box = document.createElement('div')
      box.className = 'suggest'
      const text = document.createElement('div')
      text.textContent = `渲染器建议提问：${p.text}`
      const send = document.createElement('button')
      send.textContent = '发送（模拟）'
      send.onclick = () => { log('·', `学习者确认发送：${p.text}`); box.remove() }
      const dismiss = document.createElement('button')
      dismiss.textContent = '忽略'
      dismiss.onclick = () => box.remove()
      box.append(text, send, dismiss)
      $('suggestions').append(box)
      return reply(id, {})
    }
    case 'ui/openLink':
      log('·', `渲染器请求打开链接，需用户确认（开发宿主不实际打开）：${p?.url}`)
      return reply(id, {})
    case 'state/get':
    case 'state/set': {
      if (!grants().includes('storage.plugin')) return fail(id, 'permission_denied', -32001)
      const key = `${envelope.objectId}:${p?.key}`
      if (method === 'state/get') return reply(id, { value: viewState.has(key) ? viewState.get(key) : null })
      viewState.set(key, p.value)
      return reply(id, {})
    }
    default:
      if (id !== undefined) fail(id, 'method_not_found', -32601)
  }
}

window.addEventListener('message', event => {
  // 规范 4.3：只接受来自该渲染器 iframe 的消息
  if (!iframe || event.source !== iframe.contentWindow) return
  const now = performance.now()
  if (now - windowStart > 1000) { windowStart = now; windowCount = 0 }
  if (++windowCount > MAX_PER_SECOND) return showFallback('消息频率超限，已终止渲染器')
  const message = event.data
  let size
  try { size = new Blob([JSON.stringify(message)]).size } catch { size = Infinity }
  if (size > MAX_MESSAGE_BYTES) return showFallback('单条消息超过 256 KiB，已终止渲染器')
  if (!message || message.jsonrpc !== '2.0') return log('!', '丢弃不合规消息')
  log('←', message)
  handle(message)
})

async function start() {
  manifest = await (await fetch('/manifest.json')).json()
  const renderers = manifest.contributes.renderers || []
  renderer = renderers.find(r => r.id === params.get('renderer')) || renderers[0]
  if (!renderer) { $('meta').textContent = '该插件没有渲染器贡献'; return }
  const samplePath = params.get('sample') || 'samples/deck.json'
  const sample = await (await fetch(`/plugin/${samplePath}`)).json()
  objectType = manifest.contributes.objectTypes.find(o => o.id === sample.objectType)
  envelope = {
    objectType: `${manifest.id}/${sample.objectType}`,
    schemaVersion: objectType.schemaVersion,
    objectId: newObjectId(),
    createdAt: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
    producer: { pluginId: manifest.id, pluginVersion: manifest.version },
    supersedes: null,
    fallbackText: sample.fallbackText,
    value: sample.value,
  }
  $('heading').textContent = `渲染器开发宿主 · ${manifest.id}/${renderer.id}`
  $('meta').textContent = `样例对象：${samplePath}（${envelope.objectType} ${envelope.schemaVersion}）`
  mount()
}

$('theme').onclick = () => {
  colorScheme = colorScheme === 'light' ? 'dark' : 'light'
  post({ method: 'host/themeChanged', params: { theme: theme() } })
}
$('update').onclick = () => {
  const previous = envelope.objectId
  const value = structuredClone(envelope.value)
  if (Array.isArray(value.cards)) value.cards.push({ front: '（更新）新增的一张卡', back: '对象不可变：更新会产生新对象，并记录 supersedes。' })
  envelope = { ...envelope, objectId: newObjectId(), supersedes: previous, createdAt: new Date().toISOString().replace(/\.\d+Z$/, 'Z'), value }
  post({ method: 'render/objectUpdated', params: { object: envelope } })
}
$('reload').onclick = () => {
  if (iframe) post({ method: 'render/dispose' })
  mount()
}
$('grantStorage').onchange = () => $('reload').click()

start().catch(err => log('!', `启动失败：${err}`))
