/**
 * 通知未读数、可参加考试数的刷新信号。
 * 侧栏监听 inboxSignalTick；标记已读、交卷等不跳页的操作成功后调用 requestInboxRefresh()。
 */
import { ref } from 'vue'

export const inboxSignalTick = ref(0)

export const requestInboxRefresh = () => {
  inboxSignalTick.value += 1
}
