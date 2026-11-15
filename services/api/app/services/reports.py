import csv
import io
import json
from html import escape


def comparison_csv(results):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for key in ['research_label', 'seed', 'replications', 'patient_count_per_replication', 'policy_version', 'parameters', 'input_sequence_hashes', 'comparison', 'definitions', 'limitations']:
        if key in results:
            writer.writerow(['# ' + key, json.dumps(results[key], sort_keys=True)])
    writer.writerow(['policy', 'mean_wait_minutes', 'p90_wait_minutes', 'completed_mean', 'utilisation_mean'])
    for policy, row in results['policies'].items():
        writer.writerow([policy, row['waiting_minutes']['mean'], row['waiting_minutes']['p90'], row['completed_mean'], row['utilisation_mean']])
    return buffer.getvalue()


def bar_svg(title, values, subtitle='Synthetic research demonstration — not clinical evidence'):
    maximum = max([float(v or 0) for v in values.values()] + [1.])
    height = 120 + 65 * len(values)
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="{height}" viewBox="0 0 800 {height}" role="img" aria-label="{escape(title, quote=True)}">',
        '<rect width="100%" height="100%" fill="#f7f6ef"/>',
        f'<text x="24" y="32" font-family="sans-serif" font-size="21" fill="#173e35">{escape(title)}</text>',
        f'<text x="24" y="58" font-family="sans-serif" font-size="12">{escape(subtitle)}</text>']
    for index, (label, value) in enumerate(values.items()):
        y = 90 + index * 65
        width = float(value or 0) / maximum * 460
        elements.extend([f'<text x="24" y="{y+20}" font-family="sans-serif" font-size="14">{escape(label)}</text>',
            f'<rect x="200" y="{y}" width="{width:.2f}" height="32" rx="4" fill="#176c54"/>',
            f'<text x="{210+width:.2f}" y="{y+21}" font-family="sans-serif" font-size="13">{f"{value:.2f} min" if value is not None else "No data"}</text>'])
    return ''.join(elements) + '</svg>'
