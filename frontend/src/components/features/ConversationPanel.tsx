import { EmptyState } from './EmptyState'

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
}

export interface ConversationPanelProps {
  messages?: readonly ConversationMessage[]
}

/**
 * 对话面板（Phase 2 插槽）：数据驱动占位。
 * 后续可整体替换为生成式 UI，消费方只依赖 props 接口。
 */
export function ConversationPanel({ messages = [] }: ConversationPanelProps) {
  return (
    <section aria-label="对话面板" className="space-y-3">
      {messages.map((message) => (
        <p key={message.id} className="text-body-sm">
          <span className="font-medium">{message.role === 'user' ? '我' : 'AI 建议'}</span>：
          {message.content}
        </p>
      ))}
      {messages.length === 0 ? (
        <EmptyState
          title="对话尚未开始"
          description="Phase 2 接入问答与共创界面，本阶段为插槽占位。"
        />
      ) : null}
    </section>
  )
}
