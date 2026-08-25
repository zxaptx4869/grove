import { defineManifest } from '@crxjs/vite-plugin'

export default defineManifest({
  manifest_version: 3,
  name: 'Grove 快采',
  description: '框选截图，一键发送到知林 Grove 收集箱',
  version: '0.1.0',
  action: {
    default_popup: 'src/popup/index.html',
    default_title: 'Grove 快采',
  },
  background: {
    service_worker: 'src/background.ts',
    type: 'module',
  },
  content_scripts: [
    {
      matches: ['http://*/*', 'https://*/*'],
      js: ['src/content/capture.ts'],
      css: ['src/content/capture.css'],
      run_at: 'document_idle',
    },
  ],
  permissions: ['activeTab', 'scripting', 'storage'],
  host_permissions: ['http://localhost/*', 'http://127.0.0.1/*'],
  commands: {
    capture: {
      suggested_key: { default: 'Ctrl+Shift+S', mac: 'Command+Shift+S' },
      description: '框选截图发送到 Grove',
    },
  },
  icons: {
    16: 'src/icons/icon16.png',
    48: 'src/icons/icon48.png',
    128: 'src/icons/icon128.png',
  },
})
