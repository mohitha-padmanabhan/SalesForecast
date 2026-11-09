import { useState } from 'react';
import './ForecastComparisonChart.css';

const TYPES = {consensus: 'Consensus', stat: 'Statistical Forecast', budget: 'Budget'};
const COLORS = ['#082e4e', '#d7193f', '#16846a', '#8257ac', '#c05e12', '#187db5'];
const format = value => Math.round(value).toLocaleString('en-US');

export default function ForecastComparisonChart({matrix, months, hasData}) {
  const [hiddenYears, setHiddenYears] = useState([]);
  const [hiddenTypes, setHiddenTypes] = useState([]);
  const available = matrix.filter(row => TYPES[row.type]);
  const years = [...new Set(available.map(row => row.year))];
  const series = available.map((row, index) => ({...row, color: COLORS[index % COLORS.length]}))
    .filter(row => !hiddenYears.includes(row.year) && !hiddenTypes.includes(row.type));
  const toggle = (value, setHidden) => setHidden(old => old.includes(value) ? old.filter(item => item !== value) : [...old, value]);
  const values = series.flatMap(row => row.vals);
  const minimum = Math.min(0, ...values);
  const maximum = Math.max(1, ...values);
  const padding = (maximum - minimum) * 0.08;
  const low = minimum < 0 ? minimum - padding : 0;
  const high = maximum + padding;
  const x = month => 80 + month * 77;
  const y = value => 290 - (value - low) / (high - low) * 250;
  return (
    <section className="summary-card forecast-comparison">
      <h2>Monthly Forecast Comparison</h2>
      <p>Monthly quantity in 9L cases. Select years and series to compare.</p>
      <div className="comparison-controls">
        <fieldset><legend>Years</legend>{years.map(year => <label key={year}><input type="checkbox" checked={!hiddenYears.includes(year)} onChange={() => toggle(year, setHiddenYears)} />{year}</label>)}</fieldset>
        <fieldset><legend>Series</legend>{Object.entries(TYPES).map(([type, label]) => <label key={type}><input type="checkbox" checked={!hiddenTypes.includes(type)} onChange={() => toggle(type, setHiddenTypes)} />{label}</label>)}</fieldset>
      </div>
      {!hasData ? <p role="status">No forecast data matches these filters.</p> : !series.length ? <p role="status">Select at least one year and series.</p> : <>
        <div className="comparison-plot">
          <svg viewBox="0 0 1000 340" role="img" aria-label="Monthly consensus, statistical forecast and budget comparison in 9L cases">
            <text x="80" y="18" className="chart-axis-title">Quantity (9L cases)</text>
            {Array.from({length: 6}, (_, i) => low + (high - low) * i / 5).map((value, index) => <g key={index}>
              <line x1="80" x2="927" y1={y(value)} y2={y(value)} stroke="#dce5ec" />
              <text x="72" y={y(value) + 4} textAnchor="end">{format(value)}</text>
            </g>)}
            {months.map((month, index) => <text key={month} x={x(index)} y="314" textAnchor="middle">{month}</text>)}
            {series.map(row => <g key={row.label}>
              <polyline points={row.vals.map((value, index) => `${x(index)},${y(value)}`).join(' ')} fill="none" stroke={row.color} strokeWidth="2.5" strokeDasharray={row.type === 'budget' ? '7 5' : row.type === 'stat' ? '3 3' : undefined} />
              {row.vals.map((value, index) => <circle key={index} cx={x(index)} cy={y(value)} r="4" fill={row.color} tabIndex="0" aria-label={`${row.label}, ${months[index]}, ${format(value)} 9L cases`}><title>{`${row.label} · ${months[index]} · ${format(value)} 9L cases`}</title></circle>)}
            </g>)}
          </svg>
        </div>
        <ul className="comparison-legend">{series.map(row => <li key={row.label}><span style={{backgroundColor: row.color}} />{row.label}</li>)}</ul>
      </>}
      <p className="comparison-note">The next-year Statistical Forecast uses the same budget source as the Dashboard.</p>
    </section>
  );
}
