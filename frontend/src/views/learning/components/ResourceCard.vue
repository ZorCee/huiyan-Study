<script setup lang="ts">
import { computed } from 'vue'
import {
  Star,
  StarFilled,
  Document,
  Reading,
  Picture,
  VideoPlay,
  Files,
  Pointer,
} from '@element-plus/icons-vue'
import { LearningApi } from '@/api'

type Resource = LearningApi.LearningResource

const props = defineProps<{
  resource: Resource
  canEdit: boolean
  canDelete: boolean
  showFavoriteToggle?: boolean
}>()

const emit = defineEmits<{
  (e: 'preview', r: Resource): void
  (e: 'toggle-fav', r: Resource): void
  (e: 'edit', r: Resource): void
  (e: 'delete', r: Resource): void
  (e: 'note', r: Resource): void
  (e: 'practice-case', r: Resource): void
}>()

const tagList = computed(() =>
  (props.resource.tags || '').split(',').map((t) => t.trim()).filter(Boolean)
)

const typeLabel = computed(() =>
  LearningApi.resourceTypeLabel(props.resource.resourceType, props.resource.resourceTypeText)
)

// 按文件格式区分图标（PDF / 课件 / 图片 / 视频 / 文章），不再按分类给整张卡上色
const format = computed(() => {
  const raw = (props.resource.fileType || '').toLowerCase()
  const ext = raw || (props.resource.fileUrl || '').split('?')[0].split('.').pop()?.toLowerCase() || ''
  if (ext.includes('pdf')) return { icon: Document, label: 'PDF' }
  if (/(ppt|key|doc|xls)/.test(ext)) return { icon: Files, label: '课件' }
  if (/(png|jpe?g|gif|webp|bmp|tiff?|image)/.test(ext)) return { icon: Picture, label: '图片' }
  if (/(mp4|mov|webm|avi|video)/.test(ext)) return { icon: VideoPlay, label: '视频' }
  return { icon: Reading, label: '文章' }
})
</script>

<template>
  <article class="resource-card">
    <div class="cover">
      <el-image
        v-if="resource.coverUrl"
        :src="resource.coverUrl"
        :alt="resource.title"
        fit="cover"
        class="cover-img"
      >
        <template #error>
          <div class="cover-fallback">
            <el-icon :size="36"><component :is="format.icon" /></el-icon>
            <span class="format-label">{{ format.label }}</span>
          </div>
        </template>
      </el-image>
      <div v-else class="cover-fallback" aria-hidden="true">
        <el-icon :size="36"><component :is="format.icon" /></el-icon>
        <span class="format-label">{{ format.label }}</span>
      </div>
      <div class="badges">
        <span class="kind-badge">公共学习资料</span>
        <span class="type-chip">{{ typeLabel }}</span>
      </div>
    </div>

    <div class="meta">
      <h3 class="title" :title="resource.title">{{ resource.title }}</h3>
      <p class="summary">{{ resource.summary || '暂无简介' }}</p>

      <div v-if="tagList.length" class="tags">
        <el-tag v-for="t in tagList.slice(0, 4)" :key="t" size="small" effect="plain">
          {{ t }}
        </el-tag>
      </div>

      <div class="footer">
        <span class="stat">
          <el-icon><view /></el-icon>{{ resource.viewCount }}
        </span>
        <!--
          星号以前只是个统计数字，但用户就是冲着它去点的（测试报告：「收藏的
          星号点不了」）。真正的收藏按钮在下面一排，这里让星号也能点，
          省得看着像坏的。
        -->
        <span
          v-if="showFavoriteToggle !== false"
          class="stat stat-clickable"
          :class="{ 'is-fav': resource.isFavorited }"
          :title="resource.isFavorited ? '取消收藏' : '收藏'"
          @click="emit('toggle-fav', resource)"
        >
          <el-icon><component :is="resource.isFavorited ? StarFilled : Star" /></el-icon>
          {{ resource.favoriteCount }}
        </span>
        <span v-else class="stat">
          <el-icon><star /></el-icon>{{ resource.favoriteCount }}
        </span>
        <span v-if="resource.publisherName" class="publisher">
          {{ resource.publisherName }}
        </span>
      </div>

      <div class="actions">
        <el-button size="small" type="warning" @click="emit('preview', resource)">
          去阅读
        </el-button>
        <el-button
          v-if="resource.caseId"
          size="small"
          plain
          :icon="Pointer"
          @click="emit('practice-case', resource)"
        >
          去判读这个病例
        </el-button>
        <el-button
          v-if="showFavoriteToggle !== false"
          size="small"
          :type="resource.isFavorited ? 'warning' : 'default'"
          :icon="resource.isFavorited ? StarFilled : Star"
          @click="emit('toggle-fav', resource)"
        >
          {{ resource.isFavorited ? '已收藏' : '收藏' }}
        </el-button>
        <el-button size="small" plain @click="emit('note', resource)">
          记笔记
        </el-button>
        <el-button v-if="canEdit" size="small" plain @click="emit('edit', resource)">
          编辑
        </el-button>
        <el-button
          v-if="canDelete"
          size="small"
          type="danger"
          plain
          @click="emit('delete', resource)"
        >
          删除
        </el-button>
      </div>
    </div>
  </article>
</template>

<style scoped>
/* 公共学习资料：主色固定为橙色，与教师演示病例（蓝色）区分 */
.resource-card {
  --res-accent: #fa8c16;
  display: flex;
  flex-direction: column;
  background: var(--hy-c-surface, #fff);
  border: 1px solid var(--hy-c-border, #e5e6eb);
  border-top: 3px solid var(--res-accent);
  border-radius: 10px;
  overflow: hidden;
  transition: box-shadow 0.2s, transform 0.2s;
}
.resource-card:hover {
  box-shadow: 0 8px 24px rgba(250, 140, 22, 0.14);
  transform: translateY(-2px);
}
.cover {
  position: relative;
  height: 130px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: #fff7e6;
  color: var(--res-accent);
}
.format-label {
  font-size: 12px;
  font-weight: 600;
}
.badges {
  position: absolute;
  top: 8px;
  left: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.kind-badge {
  padding: 2px 10px;
  border-radius: 10px;
  background: var(--res-accent);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
}
.type-chip {
  padding: 1px 8px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid #ffd591;
  color: #ad4e00;
  font-size: 11px;
}
.cover-img {
  width: 100%;
  height: 100%;
}
.cover-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: center;
  justify-content: center;
}
.meta {
  padding: 12px 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
}
.title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--hy-c-text, #1d2129);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
}
.summary {
  margin: 0;
  font-size: 12px;
  color: var(--hy-c-text-3, #86909c);
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  height: 36px;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.footer {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--hy-c-text-3, #86909c);
  align-items: center;
  padding-top: 6px;
  border-top: 1px dashed var(--hy-c-border, #e5e6eb);
}
.stat {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.stat-clickable {
  cursor: pointer;
  transition: color 0.15s;
}
.stat-clickable:hover {
  color: var(--el-color-warning);
}
.stat-clickable.is-fav {
  color: var(--el-color-warning);
}
.publisher {
  margin-left: auto;
  color: var(--hy-c-text-2, #4e5969);
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}
</style>
