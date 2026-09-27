import ReactEChartsCore from 'echarts-for-react/esm/core'
import * as echarts from 'echarts/core'
import { BarChart, HeatmapChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'

// Only the chart types this app uses (keeps the bundle small)
echarts.use([BarChart, LineChart, HeatmapChart, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, SVGRenderer])
import { useComputedColorScheme } from '@mantine/core'
import { useMemo } from 'react'

/** Validated categorical slots (dataviz reference palette); dark mode uses its own selected steps. */
const SERIES = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
}
/** Sequential blue ramp, light→dark (magnitude). */
export const SEQ_BLUE = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']

export function useChartColors() {
  const scheme = useComputedColorScheme('light')
  const dark = scheme === 'dark'
  return {
    dark,
    series: dark ? SERIES.dark : SERIES.light,
    positive: dark ? '#3987e5' : '#2a78d6',
    negative: dark ? '#e66767' : '#e34948',
    text: dark ? '#c3c2b7' : '#52514e',
    grid: dark ? '#2e2e2c' : '#ecebe8',
    surface: dark ? '#1a1a19' : '#fcfcfb',
  }
}

/** ECharts with recessive axes/grid, text-ink labels and a hover tooltip by default. */
export function Chart({ option, height = 260, onClick }: { option: EChartsOption; height?: number; onClick?: (dataIndex: number) => void }) {
  const c = useChartColors()
  const merged = useMemo<EChartsOption>(() => ({
    color: c.series,
    animation: false,
    backgroundColor: 'transparent',
    textStyle: { color: c.text, fontFamily: 'inherit' },
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: c.dark ? '#262624' : '#ffffff',
      borderColor: c.grid,
      textStyle: { color: c.dark ? '#ffffff' : '#0b0b0b' },
    },
    ...option,
  }), [option, c])
  return (
    <ReactEChartsCore
      echarts={echarts}
      option={merged}
      style={{ height, width: '100%', cursor: onClick ? 'pointer' : undefined }}
      notMerge
      lazyUpdate
      opts={{ renderer: 'svg' }}
      onEvents={onClick ? { click: (p: { dataIndex: number }) => onClick(p.dataIndex) } : undefined}
    />
  )
}

export const axisStyle = (c: ReturnType<typeof useChartColors>) => ({
  axisLine: { lineStyle: { color: c.grid } },
  axisTick: { show: false },
  axisLabel: { color: c.text },
  splitLine: { lineStyle: { color: c.grid } },
})
