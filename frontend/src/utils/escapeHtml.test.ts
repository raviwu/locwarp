import { describe, it, expect } from 'vitest';
import { escapeHtml } from './escapeHtml';

describe('escapeHtml', () => {
  it('escapes the five HTML-significant characters', () => {
    expect(escapeHtml('<')).toBe('&lt;');
    expect(escapeHtml('>')).toBe('&gt;');
    expect(escapeHtml('&')).toBe('&amp;');
    expect(escapeHtml('"')).toBe('&quot;');
    expect(escapeHtml("'")).toBe('&#39;');
  });

  it('escapes ampersand first so existing entities are not double-broken', () => {
    // The & rule runs before <, so a literal "<b>&" becomes &lt;b&gt;&amp;
    expect(escapeHtml('<b>&')).toBe('&lt;b&gt;&amp;');
  });

  it('escapes a script-injection attempt fully', () => {
    expect(escapeHtml('<img src=x onerror="alert(\'x\')">')).toBe(
      '&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;',
    );
  });

  it('leaves a plain string untouched', () => {
    expect(escapeHtml('Taipei 101')).toBe('Taipei 101');
  });

  it('handles the empty string', () => {
    expect(escapeHtml('')).toBe('');
  });
});
