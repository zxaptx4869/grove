import { ArrowUp, BookOpen, Check, Folder, ScanLine, Sparkles, Trees } from 'lucide-react'

export function BrowserIllustration() {
  return (
    <div
      className="intro-device-visual intro-browser-visual"
      role="img"
      aria-label="浏览器扩展示意：在网页中框选闭水试验注意事项，采集到 Grove 收集箱。"
    >
      <div className="intro-mini-browser" aria-hidden="true">
        <div className="intro-window-bar">
          <span className="intro-window-dots">
            <i />
            <i />
            <i />
          </span>
          <span className="intro-mini-address">装修知识 · 闭水试验</span>
          <Trees size={15} />
        </div>
        <div className="intro-mini-webpage">
          <span className="intro-mini-kicker">装修经验</span>
          <strong>防水做完，如何验收？</strong>
          <div className="intro-mini-lines">
            <i />
            <i />
          </div>
          <div className="intro-capture-selection">
            <span className="intro-capture-label">
              <ScanLine size={12} /> 框选采集
            </span>
            <strong>闭水试验注意事项</strong>
            <p>
              检查楼下对应位置是否渗漏，
              <br />
              记录水位，保留现场影像。
            </p>
            <i className="intro-selection-corner" />
          </div>
          <div className="intro-mini-lines">
            <i />
            <i />
          </div>
        </div>
      </div>
      <div className="intro-capture-receipt" aria-hidden="true">
        <span>
          <Check size={14} />
        </span>
        <div>
          <strong>已采集 1 张</strong>
          <small>已发送到收集箱</small>
        </div>
        <Trees size={20} />
      </div>
    </div>
  )
}

export function MobileIllustration() {
  return (
    <div
      className="intro-device-visual intro-mobile-visual"
      role="img"
      aria-label="移动 App 示意：向知识 Agent 提问闭水试验注意事项，回答建议检查渗漏、记录水位，并引用来源材料。"
    >
      <div className="intro-mini-phone" aria-hidden="true">
        <div className="intro-phone-speaker" />
        <div className="intro-phone-header">
          <Trees size={18} />
          <strong>知识 Agent</strong>
        </div>
        <div className="intro-phone-scope">
          <Folder size={12} /> 新房装修
        </div>
        <div className="intro-phone-question">闭水试验要注意什么？</div>
        <div className="intro-phone-answer">
          <span>
            <Sparkles size={13} /> Grove
          </span>
          <p>根据你收藏的资料：</p>
          <p>
            <b>检查渗漏</b>，记录水位，
            <br />
            保留现场影像。<sup> [1]</sup>
          </p>
          <div className="intro-phone-citation">
            <BookOpen size={12} />
            <span>闭水试验注意事项</span>
          </div>
        </div>
        <div className="intro-phone-compose">
          <span>继续提问…</span>
          <ArrowUp size={14} />
        </div>
        <div className="intro-phone-home" />
      </div>
    </div>
  )
}

export function DesktopIllustration() {
  return (
    <div
      className="intro-device-visual intro-desktop-visual"
      role="img"
      aria-label="桌面 Web 示意：确认台并排展示闭水试验原始材料与待确认 AI 候选，推荐归属新房装修项目的防水目录，由用户审阅确认。"
    >
      <div className="intro-mini-desktop" aria-hidden="true">
        <div className="intro-window-bar">
          <Trees size={16} />
          <strong>知林 Grove</strong>
          <span>确认台</span>
        </div>
        <div className="intro-desktop-workspace">
          <div className="intro-desktop-source">
            <span className="intro-mini-kicker">原始材料</span>
            <strong>闭水试验注意事项</strong>
            <div className="intro-source-thumbnail">
              <div />
              <i />
              <i />
            </div>
            <p>
              检查渗漏，记录水位，
              <br />
              保留现场影像。
            </p>
          </div>
          <div className="intro-desktop-candidate">
            <span className="intro-mini-ai">
              <Sparkles size={12} /> AI 候选 · 待确认
            </span>
            <strong>检查渗漏并留存记录</strong>
            <p>
              检查楼下对应位置，
              <br />
              保留水位与现场记录。
            </p>
            <div className="intro-mini-routing">
              <span>推荐归属</span>
              <b>
                <Folder size={12} /> 新房装修
              </b>
              <span>施工与验收 / 防水</span>
            </div>
            <span className="intro-mini-review">
              <Check size={12} /> 人工审阅确认
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
