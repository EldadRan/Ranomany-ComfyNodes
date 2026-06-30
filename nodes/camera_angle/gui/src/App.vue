<template>
  <div class="qwen-container">
    <SceneCanvas :init-scene="initScene" />
    <ControlPanel
      :azimuth="azimuth"
      :elevation="elevation"
      :distance="distance"
      @update:azimuth="azimuth = $event"
      @update:elevation="elevation = $event"
      @update:distance="distance = $event"
      @reset="reset"
    />
  </div>
</template>

<script setup lang="ts">
import SceneCanvas from './components/SceneCanvas.vue'
import ControlPanel from './components/ControlPanel.vue'
import { useCameraWidget } from './composables/useCameraWidget'
import type { CameraState } from './types'

const props = defineProps<{
  initialState?: Partial<CameraState>
  onStateChange?: (state: CameraState) => void
}>()

const {
  azimuth,
  elevation,
  distance,
  initScene,
  setState,
  updateImage,
  setCameraView,
  reset,
  cleanup
} = useCameraWidget(props.initialState, props.onStateChange)

defineExpose({ updateImage, setCameraView, setState, cleanup })
</script>

<style scoped>
.qwen-container {
  width: 100%;
  height: 100%;
  position: relative;
  background: #0a0a0f;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  border-radius: 8px;
  overflow: hidden;
}
</style>
