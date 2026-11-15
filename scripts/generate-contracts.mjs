// Deterministic, dependency-free converter for the OpenAPI 3.1 schema subset used here.
import {readFileSync, writeFileSync} from 'node:fs';
const schemas = JSON.parse(readFileSync(new URL('../docs/API_OPENAPI.json',import.meta.url),'utf8')).components.schemas;
function type(s) {
  if ('const' in s) return JSON.stringify(s.const);
  if (s.$ref) return s.$ref.split('/').at(-1);
  if (s.enum) return s.enum.map(v=>JSON.stringify(v)).join(' | ');
  if (s.anyOf || s.oneOf) return (s.anyOf || s.oneOf).map(type).join(' | ');
  if (s.allOf) return s.allOf.map(type).join(' & ');
  if (s.type==='array') return s.prefixItems ? `[${s.prefixItems.map(type).join(', ')}]` : `Array<${type(s.items || {})}>`;
  if (s.type==='object' || s.properties) {
    if (!s.properties) return `Record<string, ${typeof s.additionalProperties==='object' ? type(s.additionalProperties) : 'unknown'}>`;
    return `{ ${Object.entries(s.properties).map(([k,v])=>`${JSON.stringify(k)}${s.required?.includes(k)?'':'?'}: ${type(v)};`).join(' ')} }`;
  }
  return {integer:'number',number:'number',string:'string',boolean:'boolean',null:'null'}[s.type] || 'unknown';
}
const text='// GENERATED from docs/API_OPENAPI.json — run make contracts. Do not edit.\n'+Object.entries(schemas).sort(([a],[b])=>a.localeCompare(b)).map(([name,s])=>`export type ${name} = ${type(s)};`).join('\n')+'\n';
writeFileSync(new URL('../apps/web/src/lib/generated.ts',import.meta.url),text);
console.log(`Generated ${Object.keys(schemas).length} API schema types`);
