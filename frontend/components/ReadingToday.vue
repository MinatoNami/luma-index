<script setup lang="ts">
import { goalPercent, type Activity } from '~/composables/useNotebook'

/**
 * Today, at a glance, beside the welcome.
 *
 * This used to be the first panel on the home page, which put a chart between
 * the reader and the book they came back to finish — on a phone, the resume
 * card ended up below the fold. The home page's job is "where was I"; how much
 * you have read today is worth a glance, not the top of the page. So it is a
 * ring and a streak here, in Apple Books' shape, and the week is further down.
 */
const props = defineProps<{ activity: Activity }>()

const goal = computed(() => props.activity.goal_pages)
const pages = computed(() => props.activity.today_pages)
const percent = computed(() => goalPercent(pages.value, goal.value))
const met = computed(() => goal.value > 0 && pages.value >= goal.value)
const streak = computed(() => props.activity.streak.current)

// The ring is drawn as a circle's stroke; the dash is how much of it to draw.
const R = 18
const CIRCUMFERENCE = 2 * Math.PI * R
const dash = computed(() => `${(percent.value / 100) * CIRCUMFERENCE} ${CIRCUMFERENCE}`)

const pageWord = (n: number) => (n === 1 ? 'page' : 'pages')
</script>

<template>
  <div class="today">
    <div class="goal">
      <svg v-if="goal" class="ring" viewBox="0 0 44 44" width="44" height="44" role="progressbar"
           :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100"
           :aria-label="`Today's goal: ${pages} of ${goal} pages`">
        <circle class="track" cx="22" cy="22" :r="R" />
        <circle :class="['arc', { met }]" cx="22" cy="22" :r="R" :stroke-dasharray="dash" />
      </svg>
      <span class="words">
        <strong>{{ pages }}</strong>
        <template v-if="goal"> of {{ goal }} {{ pageWord(goal) }} today</template>
        <template v-else> {{ pageWord(pages) }} today</template>
        <span v-if="met" class="met"><AppIcon name="check" :size="13" /> Goal met</span>
        <NuxtLink v-else-if="!goal" class="set quiet-link" to="/settings#reading-goal">
          Set a goal
        </NuxtLink>
      </span>
    </div>

    <span class="divider" aria-hidden="true" />

    <div :class="['streak', { lit: streak > 0 }]">
      <AppIcon :name="streak > 0 ? 'flame-filled' : 'flame'" :size="18" />
      <span class="words">
        <template v-if="streak > 0"><strong>{{ streak }}</strong> {{ streak === 1 ? 'day' : 'days' }} in a row</template>
        <template v-else>No streak yet</template>
      </span>
    </div>
  </div>
</template>

<style scoped>
.today {
  display: inline-flex; align-items: center; gap: var(--space-4);
  padding: var(--space-2) var(--space-4) var(--space-2) var(--space-2);
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-full); box-shadow: var(--shadow-sm);
  font-size: var(--text-sm); color: var(--text-secondary);
}
.goal, .streak { display: flex; align-items: center; gap: var(--space-2); }
.goal:not(:has(.ring)) { padding-left: var(--space-2); }
.words { display: inline-flex; align-items: baseline; flex-wrap: wrap; gap: 0 var(--space-1); }
strong { color: var(--text); font-size: var(--text-md); font-weight: 600;
         font-variant-numeric: tabular-nums; }

.ring { flex: none; transform: rotate(-90deg); }
.ring circle { fill: none; stroke-width: 4; }
.track { stroke: var(--surface-sunken); }
.arc { stroke: var(--accent); stroke-linecap: round;
       transition: stroke-dasharray var(--duration) var(--ease); }
.arc.met { stroke: var(--success); }

.met { display: inline-flex; align-items: center; gap: 2px; margin-left: var(--space-1);
       color: var(--success); font-weight: 500; }
.set { margin-left: var(--space-1); }

.divider { width: 1px; align-self: stretch; margin: var(--space-1) 0; background: var(--border); }

.streak { color: var(--text-tertiary); }
.streak.lit .icon { color: var(--flame); }

@media (max-width: 40rem) {
  .today { display: flex; width: 100%; justify-content: space-between;
           border-radius: var(--radius-lg); }
}
</style>
