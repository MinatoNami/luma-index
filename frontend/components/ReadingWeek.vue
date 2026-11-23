<script setup lang="ts">
import { weekday, weekScale, type Activity } from '~/composables/useNotebook'

/**
 * The last seven days, and the year so far.
 *
 * One series, so one hue and no legend — the section heading says what it is.
 * Today's bar carries its number, because today is the one the reader is
 * acting on; the rest are a hover away, and all seven are in a table for
 * anyone not reading bars. A day that met the goal says so with a tick beside
 * its name rather than a different colour, so it does not depend on telling
 * two shades apart. The goal itself is a hairline, drawn inside the plot with
 * headroom above it so it never reads as the plot's top edge.
 */
const props = defineProps<{ activity: Activity }>()

const goal = computed(() => props.activity.goal_pages)
const week = computed(() => props.activity.week)

// 15% headroom over the tallest of the bars and the goal, so the top bar and
// the goal line both sit visibly inside the frame.
const HEADROOM = 1.15
const heights = computed(() => weekScale(week.value, goal.value).map(h => h / HEADROOM))
const goalAt = computed(() => {
  if (!goal.value) return null
  const top = Math.max(goal.value, ...week.value.map(d => d.pages), 1)
  return goal.value / top / HEADROOM
})

const total = computed(() => week.value.reduce((sum, d) => sum + d.pages, 0))
const activeDays = computed(() => week.value.filter(d => d.pages > 0).length)
const year = computed(() => props.activity.year)

const isToday = (i: number) => i === week.value.length - 1
const metGoal = (pages: number) => goal.value > 0 && pages >= goal.value
const dayLabel = (iso: string, i: number) => (isToday(i) ? 'Today' : weekday(iso))
const pages = (n: number) => `${n.toLocaleString()} ${n === 1 ? 'page' : 'pages'}`
</script>

<template>
  <div class="panel week">
    <div class="numbers">
      <div class="stat">
        <span class="value">{{ total.toLocaleString() }}</span>
        <span class="caption">pages this week</span>
      </div>
      <div class="stat">
        <span class="value">{{ activeDays }}<span class="of">/7</span></span>
        <span class="caption">days with reading</span>
      </div>
      <div class="stat">
        <span class="value">{{ activity.streak.longest }}</span>
        <span class="caption">longest streak</span>
      </div>
    </div>

    <figure class="chart">
      <div class="plot" aria-hidden="true">
        <span v-if="goalAt !== null" class="goal-line" :style="{ bottom: `${goalAt * 100}%` }">
          <span class="goal-tag">Goal {{ goal }}</span>
        </span>
        <div v-for="(day, i) in week" :key="day.date" :class="['column', { today: isToday(i) }]">
          <span v-if="isToday(i) && day.pages" class="direct"
                :style="{ bottom: `calc(${heights[i] * 100}% + 4px)` }">{{ day.pages }}</span>
          <span class="bar" :class="{ empty: !day.pages }"
                :style="{ height: day.pages ? `max(4px, ${heights[i] * 100}%)` : '2px' }" />
          <span class="tip">{{ dayLabel(day.date, i) }} · {{ pages(day.pages) }}<template
            v-if="metGoal(day.pages)"> · goal met</template></span>
        </div>
      </div>
      <div class="days" aria-hidden="true">
        <span v-for="(day, i) in week" :key="day.date" :class="{ now: isToday(i) }">
          <AppIcon v-if="metGoal(day.pages)" name="check" :size="11" class="tick" />
          {{ dayLabel(day.date, i) }}
        </span>
      </div>
      <!-- The table view: the same seven numbers, for a screen reader. -->
      <table class="sr-only">
        <caption>Pages read each day, last seven days</caption>
        <thead>
          <tr>
            <th scope="col">Day</th><th scope="col">Pages</th>
            <th v-if="goal" scope="col">Goal met</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(day, i) in week" :key="day.date">
            <th scope="row">{{ dayLabel(day.date, i) }}</th>
            <td>{{ day.pages }}</td>
            <td v-if="goal">{{ metGoal(day.pages) ? 'Yes' : 'No' }}</td>
          </tr>
        </tbody>
      </table>
    </figure>

    <p v-if="year.pages || year.books_finished" class="year">
      <span>{{ new Date().getFullYear() }} so far</span>
      {{ pages(year.pages) }}<template v-if="year.days"> over {{ year.days }}
        {{ year.days === 1 ? 'day' : 'days' }}</template><template
        v-if="year.books_finished"> · {{ year.books_finished }}
        {{ year.books_finished === 1 ? 'book' : 'books' }} finished</template>
    </p>
  </div>
</template>

<style scoped>
.week {
  display: grid; gap: var(--space-4) var(--space-6);
  grid-template-columns: minmax(0, 14rem) minmax(0, 1fr);
  padding: var(--space-4) var(--space-5);
}

.numbers { display: grid; gap: var(--space-3); align-content: start; }
.stat { display: flex; flex-direction: column; }
.value {
  font-size: var(--text-lg); font-weight: 600; letter-spacing: -0.01em;
  font-variant-numeric: tabular-nums; color: var(--text);
}
.of { font-size: var(--text-sm); font-weight: 400; color: var(--text-tertiary); }
.caption { font-size: var(--text-sm); color: var(--text-secondary); }

.chart { margin: 0; display: flex; flex-direction: column; gap: var(--space-2); min-width: 0; }

.plot {
  position: relative; height: 112px;
  display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px;
  align-items: end;
  /* The baseline: hairline, solid, one step off the surface. */
  border-bottom: 1px solid var(--chart-grid);
}
.column {
  position: relative; height: 100%;
  display: flex; align-items: flex-end; justify-content: center;
}
.bar {
  width: min(24px, 64%);
  background: var(--chart-bar);
  /* Rounded at the data end, square at the baseline it grows from. */
  border-radius: 4px 4px 0 0;
}
.bar.empty { background: var(--chart-grid); border-radius: 0; }

.direct {
  position: absolute; left: 0; right: 0; text-align: center;
  font-size: var(--text-xs); font-weight: 600; color: var(--text);
  font-variant-numeric: tabular-nums; pointer-events: none;
}

.goal-line {
  position: absolute; left: 0; right: 0; height: 0; z-index: 1;
  border-top: 1px solid var(--text-tertiary);
  pointer-events: none;
}
.goal-tag {
  position: absolute; right: 0; bottom: 3px;
  padding: 0 var(--space-1);
  background: var(--surface); color: var(--text-tertiary);
  font-size: 0.6875rem; line-height: 1.2;
}

/* Per-bar hover: the whole column is the target, not the 4px stub of a
   quiet day. */
.tip {
  position: absolute; bottom: calc(100% + 6px); left: 50%; transform: translateX(-50%);
  padding: 3px var(--space-2); white-space: nowrap; z-index: 2;
  background: var(--text); color: var(--bg);
  border-radius: var(--radius-sm); font-size: var(--text-xs);
  opacity: 0; pointer-events: none;
  transition: opacity var(--duration-fast) var(--ease);
}
.column:first-child .tip { left: 0; transform: none; }
.column:last-child .tip { left: auto; right: 0; transform: none; }
.column:hover .tip { opacity: 1; }
.column:hover .bar:not(.empty) { filter: brightness(1.12); }

.days { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; text-align: center; }
.days span {
  display: inline-flex; align-items: center; justify-content: center; gap: 2px;
  font-size: var(--text-xs); color: var(--text-tertiary);
}
.days .now { color: var(--text); font-weight: 600; }
.tick { color: var(--success); }

.year {
  grid-column: 1 / -1; margin: 0; padding-top: var(--space-3);
  border-top: 1px solid var(--border);
  font-size: var(--text-sm); color: var(--text-secondary);
}
.year span {
  margin-right: var(--space-2);
  font-size: var(--text-xs); font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase; color: var(--text-tertiary);
}

@media (max-width: 48rem) {
  .week { grid-template-columns: minmax(0, 1fr); padding: var(--space-4); }
  .numbers { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
</style>
