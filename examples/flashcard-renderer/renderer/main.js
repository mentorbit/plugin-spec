// 闪卡渲染器：演示 mentorbit.renderer/0.1 消息协议（见规范第 04 章）
'use strict'

const PROTOCOL = 'mentorbit.renderer/0.1'
const pending = new Map() // 渲染器发出的请求 id -> 回调
let nextId = 1
let deck = null
let index = 0
let showBack = false
let canStore = false

const $ = id => document.getElementById(id)

function send(message) {
  // 沙箱 iframe 为不透明源，目标源只能写 '*'；宿主负责校验 event.source
  window.parent.postMessage({ jsonrpc: '2.0', ...message }, '*')
}

function request(method, params) {
  const id = `r${nextId++}`
  send({ id, method, params })
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }))
}

function notify(method, params) {
  send({ method, params })
}

function applyTheme(theme) {
  const t = theme.tokens
  const root = document.documentElement.style
  root.setProperty('--bg', t.background)
  root.setProperty('--fg', t.foreground)
  root.setProperty('--muted', t.muted)
  root.setProperty('--accent', t.accent)
  root.setProperty('--border', t.border)
  root.setProperty('--font', t.fontFamily)
  root.setProperty('--size', t.fontSizeBase)
}

function render() {
  if (!deck) return
  const card = deck.cards[index]
  // 只用 textContent 写入对象内容，避免把数据当作 HTML 解析
  $('title').textContent = deck.title
  $('side').textContent = showBack ? '背面' : '正面（点击翻面）'
  $('text').textContent = showBack ? card.back : card.front
  $('pos').textContent = `${index + 1} / ${deck.cards.length}`
  $('prev').disabled = index === 0
  $('next').disabled = index === deck.cards.length - 1
  notify('ui/resize', { height: Math.ceil(document.body.scrollHeight) })
}

function go(delta) {
  index = Math.min(deck.cards.length - 1, Math.max(0, index + delta))
  showBack = false
  render()
  // 未获 storage.plugin 授权时不保存视图状态，功能照常可用
  if (canStore) request('state/set', { key: 'index', value: index }).catch(() => {})
}

async function onInit(params) {
  deck = params.object.value
  canStore = params.grants.includes('storage.plugin')
  applyTheme(params.theme)
  if (canStore) {
    try {
      const saved = await request('state/get', { key: 'index' })
      if (Number.isInteger(saved.value) && saved.value < deck.cards.length) index = saved.value
    } catch {
      // 读取失败时从第一张开始
    }
  }
  render()
}

window.addEventListener('message', event => {
  if (event.source !== window.parent) return
  const msg = event.data
  if (!msg || msg.jsonrpc !== '2.0') return

  // 宿主对渲染器请求的响应
  if ('id' in msg && !('method' in msg)) {
    const waiter = pending.get(msg.id)
    if (!waiter) return
    pending.delete(msg.id)
    if (msg.error) waiter.reject(msg.error)
    else waiter.resolve(msg.result)
    return
  }

  switch (msg.method) {
    case 'render/init':
      onInit(msg.params).then(
        () => send({ id: msg.id, result: {} }),
        err => send({ id: msg.id, error: { code: -32603, message: String(err), data: { reason: 'internal_error' } } }),
      )
      break
    case 'render/objectUpdated':
      deck = msg.params.object.value
      index = Math.min(index, deck.cards.length - 1)
      render()
      break
    case 'host/themeChanged':
      applyTheme(msg.params.theme)
      break
    case 'render/dispose':
      pending.clear()
      break
    default:
      if ('id' in msg) send({ id: msg.id, error: { code: -32601, message: 'method not found', data: { reason: 'method_not_found' } } })
  }
})

$('card').addEventListener('click', () => { showBack = !showBack; render() })
$('card').addEventListener('keydown', e => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); showBack = !showBack; render() }
})
$('prev').addEventListener('click', () => go(-1))
$('next').addEventListener('click', () => go(1))
$('ask').addEventListener('click', () => {
  // 建议由宿主展示给学习者，确认后才会发送（规范 4.5）
  const card = deck && deck.cards[index]
  if (card) request('ui/suggestPrompt', { text: `请再讲讲：${card.front}` }).catch(() => {})
})

notify('ui/ready', { protocol: PROTOCOL })
