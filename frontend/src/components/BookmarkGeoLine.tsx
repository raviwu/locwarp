import React from 'react';
import { useI18n } from '../i18n';
import { countryName, formatGmtOffset } from '../utils/geoFormat';

interface BookmarkGeoLineProps {
  countryCode?: string;
  city?: string;
  timezone?: string;
}

// Line 2 of a bookmark row: flag · country · city · GMT offset.
// Each segment is omitted when its data is missing, so a bookmark the
// reconciliation sweep has not reached yet (or an ocean point) just
// shows fewer parts instead of empty separators.
export const BookmarkGeoLine: React.FC<BookmarkGeoLineProps> = ({
  countryCode,
  city,
  timezone,
}) => {
  const { lang } = useI18n();
  const country = countryName(countryCode, lang);
  const offset = formatGmtOffset(timezone);
  const textParts = [country, city, offset].filter(Boolean);

  if (!countryCode && textParts.length === 0) return null;

  return (
    <span
      style={{
        fontSize: 10,
        opacity: 0.55,
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        minWidth: 0,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}
    >
      {countryCode && (
        <img
          src={`https://flagcdn.com/w20/${countryCode}.png`}
          alt={countryCode.toUpperCase()}
          width={14}
          height={10}
          style={{
            borderRadius: 2,
            flexShrink: 0,
            boxShadow: '0 0 0 1px rgba(255,255,255,0.12)',
          }}
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = 'none';
          }}
        />
      )}
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {textParts.join(' · ')}
      </span>
    </span>
  );
};
