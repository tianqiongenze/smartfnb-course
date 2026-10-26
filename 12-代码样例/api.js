import axios from 'axios'
export const http = axios.create({ baseURL: '/', timeout: 30000 })

http.interceptors.request.use(cfg => {
  const t = localStorage.getItem('token')
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

export async function login(username, password) {
  const { data } = await http.post('/api/login', { username, password })
  localStorage.setItem('token', data.token)
  localStorage.setItem('user', data.user)
  return data
}

// D-05: Spring GraphQL 仅接受 POST, GET 形式返回 405/400 — 改为统一 POST
export const stores = () => http.post('/graphql', { query: '{stores{id,name,city}}' }).then(r => r.data.data.stores)
export const diffReport = (storeId, date) => http.post('/graphql', {
  query: `query($s:Int,$d:String!){ diffReport(storeId:$s,date:$d,limit:60){
    date storeId alertCount lines{ingId ingName category theoGram actualGram diffPct level} } }`,
  variables: { s: storeId, d: date }
}).then(r => r.data.data.diffReport)
export const alerts = (date) => http.post('/graphql', {
  query: `query($d:String!){ alerts(date:$d){ id diffDate storeId ingName diffPct level status theoGram actualGram } }`,
  variables: { d: date }
}).then(r => r.data.data.alerts)
export const ackAlert = (id) => http.post('/graphql', {
  query: `mutation($id:String!){ ackAlert(id:$id) }`, variables: { id: id }
}).then(r => r.data.data.ackAlert)

/** 智能体SSE聊天(POST + fetch流解析) */
export async function agentChat(payload, onEvent) {
  const resp = await fetch('/api/agent/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  const reader = resp.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2)
      const line = chunk.split('\n').find(l => l.startsWith('data: ') || l.startsWith('data:'))
      if (line) onEvent(JSON.parse(line.replace(/^data:\s?/, '')))
    }
  }
}
