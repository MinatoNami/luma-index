<script setup lang="ts">
import { goalPercent, streakLabel, weekday, weekScale, type Activity } from '~/composables/useNotebook'

/**
 * Today, the streak, and the last seven days.
 *
 * Apple Books' reading goal and Kindle's streaks, sized for a home page: three
 * facts and a week, not a dashboard. The week is one series, so one hue and no
 * legend — the heading says what it is — with a hairline at the goal when
 * there is one, and every day's number in a table for anyone not reading bars.
 */
const props = defineProps<{ activity: Activity }>()

const goal = computed(() => props.activity.goal_pages)
const today = computed(() => props.activity.today_pages)
const percent = computed(() => goalPercent(today.value, goal.value))
const met = computed(() => goal.value > 0 && today.value >= goal.value)

const heights = computed(() => weekScale(props.activity.week, goal.value))
// Where the goal line sits, as a fraction of the plot's height.
const goalAt = computed(() => {
  if (!goal.value) return null
  const top = Math.max(goal.value, ...props.activity.week.map(d => d.pages), 1)
  return goal.value / top
})

const year = computed(() => props.activity.year)
const yearLine = computed(() => {
  const { pages, days, books_finished: finished } = year.value
  const parts = [`${pages.toLocaleString()} ${pages === 1 ? 'page' : 'pages'}`]
  if (days) parts[0] += ` over ${days} ${days === 1 ? 'day' : 'days'}`
  if (finished) parts.push(`${finished} ${finished === 1 ? 'book' : 'books'} finished`)
  return parts.join(' · ')
})

function dayLabel(iso: string, index: number): string {
  return index === props.activity.week.length - 1 ? 'Today' : weekday(iso)
}
</script>

<template>
  <section class="panel activity" aria-labelledby="activity-heading">
    <h2 id="activity-heading" class="sr-only">Reading activity</h2>

    <div class="facts">
      <div class="fact today">
        <span class="label">Today</span>
        <span class="figure">
          <strong>{{ today }}</strong>
          <span class="unit">{{ goal ? `of ${goal} pages` : (today === 1 ? 'page' : 'pages') }}</span>
        </span>
        <template v-if="goal">
          <span class="meter" role="progressbar" :aria-valuenow="percent" aria-valuemin="0"
                aria-valuemax="100" :aria-label="`Daily goal: ${percent} per cent`">
            <span class="fill" :style="{ width: `${percent}%` }" />
          </span>
          <span v-if="met" class="met"><AppIcon name="check" :size="14" /> Goal met</span>
          <span v-else class="hint">{{ goal - today }} to go</span>
        </template>
        <NuxtLink v-else class="hint quiet-link" to="/settings#reading-goal">Set a daily goal</NuxtLink>
      </div>

      <div class="fact streak">
        <span class="label">Streak</span>
        <span class="figure">
          <AppIcon name="flame" :size="20" :class="{ lit: activity.streak.current > 0 }" />
          <strong>{{ activity.streak.current }}</strong>
        </span>
        <span class="hint">{{ streakLabel(activity.streak.current) }}</span>
        <span v-if="activity.streak.longest > activity.streak.current" class="hint">
          Longest {{ activity.streak.longest }}
        </span>
      </div>
    </div>

    <figure class="week">
      <figcaption class="label">Pages, last 7 days</figcaption>
      <div class="plot" aria-hidden="true">
        <span v-if="goalAt !== null" class="goal-line" :style="{ bottom: `${goalAt * 100}%` }">
          <span class="goal-tag">Goal {{ goal }}</span>
        </span>
        <div v-for="(day, i) in activity.week" :key="day.date" class="column">
          <span class="bar" :class="{ empty: !day.pages }"
                :style="{ height: day.pages ? `max(4px, ${heights[i] * 100}%)` : '2px' }" />
          <span class="tip">{{ dayLabel(day.date, i) }} · {{ day.pages }}
            {{ day.pages === 1 ? 'page' : 'pages' }}</span>
        </div>
      </div>
      <div class="days" aria-hidden="true">
        <span v-for="(day, i) in activity.week" :key="day.date"
              :class="{ now: i === activity.week.length - 1 }">{{ dayLabel(day.date, i) }}</span>
      </div>
      <!-- The table view: the same seven numbers, for a screen reader. -->
      <table class="sr-only">
        <caption>Pages read each day, last seven days</caption>
        <thead><tr><th scope="col">Day</th><th scope="col">Pages</th></tr></thead>
        <tbody>
          <tr v-for="(day, i) in activity.week" :key="day.date">
            <th scope="row">{{ dayLabel(day.date, i) }}</th><td>{{ day.pages }}</td>
          </tr>
        </tbody>
      </table>
    </figure>

    <p v-if="year.pages || year.books_finished" class="year tertiary">
      This year: {{ yearLine }}
    </p>
  </section>
</template>

<style scoped>
.activity {
  display: grid; gap: var(--space-4) var(--space-6);
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr);
  padding: var(--space-4) var(--space-5);
}

.label {
  display: block;
  font-size: var(--text-xs); font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase; color: var(--text-tertiary);
}

.facts { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-5); }
.fact { display: flex; flex-direction: column; gap: var(--space-1); min-width: 0; }

.figure { display: flex; align-items: baseline; gap: var(--space-2); }
.figure strong { font-size: 1.75rem; line-height: 1.1; letter-spacing: -0.02em; font-weight: 600; }
.unit { font-size: var(--text-sm); color: var(--text-secondary); }
.streak .figure { align-items: center; gap: var(--space-1); }
.streak .icon { color: var(--text-tertiary); }
.streak .icon.lit { color: var(--warning); }

.hint { font-size: var(--text-sm); color: var(--text-secondary); }
a.hint { color: var(--accent-text); align-self: flex-start; display: inline-flex; align-items: center; }
.met { display: inline-flex; align-items: center; gap: var(--space-1);
       font-size: var(--text-sm); font-weight: 500; color: var(--success); }

.meter {
  display: block; height: 6px; margin: var(--space-1) 0;
  border-radius: var(--radius-full); background: var(--surface-sunken); overflow: hidden;
}
.fill { display: block; height: 100%; background: var(--accent); border-radius: var(--radius-full); }

/* -- the week ------------------------------------------------------------- */

.week { margin: 0; display: flex; flex-direction: column; gap: var(--space-2); min-width: 0; }

.plot {
  position: relative; height: 72px;
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
  width: min(24px, 70%);
  background: var(--chart-bar);
  /* Rounded at the data end, square at the baseline it grows from. */
  border-radius: 4px 4px 0 0;
}
.bar.empty { background: var(--chart-grid); border-radius: 0; }

.goal-line {
  position: absolute; left: 0; right: 0; height: 0; z-index: 1;
  border-top: 1px solid var(--text-tertiary);
  pointer-events: none;
}
.goal-tag {
  position: absolute; right: 0; bottom: 2px;
  padding: 0 var(--space-1);
  background: var(--surface); color: var(--text-tertiary);
  font-size: 0.6875rem; line-height: 1.2;
}

/* Per-bar hover: the whole column is the target, not the 4px stub of a
   quiet day. */
.tip {
  position: absolute; bottom: calc(100% + 4px); left: 50%; transform: translateX(-50%);
  padding: 2px var(--space-2); white-space: nowrap; z-index: 2;
  background: var(--text); color: var(--bg);
  border-radius: var(--radius-sm); font-size: var(--text-xs);
  opacity: 0; pointer-events: none;
  transition: opacity var(--duration-fast) var(--ease);
}
.column:hover .tip { opacity: 1; }
.column:hover .bar:not(.empty) { filter: brightness(1.12); }

.days { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; text-align: center; }
.days span { font-size: 0.6875rem; color: var(--text-tertiary); }
.days .now { color: var(--text-secondary); font-weight: 600; }

.year { grid-column: 1 / -1; margin: 0; font-size: var(--text-sm);
        padding-top: var(--space-3); border-top: 1px solid var(--border); }

@media (max-width: 48rem) {
  .activity { grid-template-columns: minmax(0, 1fr); padding: var(--space-4); }
}
</style>
