import React, { useState, useMemo, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ComposedChart, Bar, BarChart, Legend, ReferenceArea } from 'recharts';

export default function GarminSleepAnalyzer() {
  const [sleepData, setSleepData] = useState([]);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState(null);
  const [activeChart, setActiveChart] = useState('rem');
  const [savedFiles, setSavedFiles] = useState([]);
  const [currentFileName, setCurrentFileName] = useState('');
  const [uploadExpanded, setUploadExpanded] = useState(true); // Collapsible upload section
  
  // Date range state
  const [dateRange, setDateRange] = useState({ start: '', end: '' });
  const [availableDates, setAvailableDates] = useState({ min: '', max: '' });
  
  // View mode: 'days', 'weeks', 'months'
  const [viewMode, setViewMode] = useState('weeks');
  
  // Chart drag selection
  const [selectStart, setSelectStart] = useState(null);
  const [selectEnd, setSelectEnd] = useState(null);
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectionStats, setSelectionStats] = useState(null); // For selection popup
  
  // Comparison mode
  const [compareMode, setCompareMode] = useState(false);
  const [period1, setPeriod1] = useState({ start: '', end: '' });
  const [period2, setPeriod2] = useState({ start: '', end: '' });
  
  // Date picker modal
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [compareType, setCompareType] = useState('previous'); // 'previous', 'year', 'custom'
  const [activePreset, setActivePreset] = useState(null); // Track which preset is selected
  const [editingPeriod, setEditingPeriod] = useState(null); // null, 1, or 2 - which period's range picker is open
  const [dragPeriod, setDragPeriod] = useState({ dragging: false, startX: 0, startDate: '', currentDate: '' }); // For drag selection

  // Load saved files list on mount
  useEffect(() => {
    const saved = localStorage.getItem('garmin_saved_files');
    if (saved) {
      setSavedFiles(JSON.parse(saved));
    }
  }, []);

  // Update available dates when data changes
  useEffect(() => {
    if (sleepData.length > 0) {
      const dates = sleepData.map(d => d.calendarDate).sort();
      const minDate = dates[0];
      const maxDate = dates[dates.length - 1];
      setAvailableDates({ min: minDate, max: maxDate });
      
      // Default to 3 months (90 days) view
      const end = new Date(maxDate);
      const start = new Date(end);
      start.setDate(start.getDate() - 89); // 90 days including end date
      const startStr = start.toISOString().split('T')[0];
      // Make sure start isn't before minDate
      const finalStart = startStr < minDate ? minDate : startStr;
      setDateRange({ 
        start: finalStart, 
        end: maxDate 
      });
      // Set active preset
      setActivePreset(finalStart === minDate ? 'all' : '3mo');
      
      // Set default comparison periods (last 2 weeks vs previous 2 weeks)
      const endDate = new Date(maxDate);
      const midDate = new Date(endDate);
      midDate.setDate(midDate.getDate() - 14);
      const startDate = new Date(midDate);
      startDate.setDate(startDate.getDate() - 14);
      
      setPeriod2({ start: midDate.toISOString().split('T')[0], end: maxDate });
      setPeriod1({ start: startDate.toISOString().split('T')[0], end: midDate.toISOString().split('T')[0] });
      
      // Auto-collapse upload section once data is loaded
      setUploadExpanded(false);
    }
  }, [sleepData]);

  const [loadInfo, setLoadInfo] = useState(null);
  const [mergeMode, setMergeMode] = useState(false);

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    setError(null);
    
    const files = Array.from(e.dataTransfer.files);
    const jsonFiles = files.filter(f => f.name.endsWith('.json'));
    
    if (jsonFiles.length === 0) {
      setError('Please drop JSON files');
      return;
    }

    Promise.all(jsonFiles.map(file => {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => {
          try {
            const data = JSON.parse(e.target.result);
            const records = Array.isArray(data) ? data : [data];
            // Get date range from this file for debugging
            const dates = records.filter(d => d.calendarDate).map(d => d.calendarDate).sort();
            resolve({ 
              fileName: file.name, 
              data: records,
              dateRange: dates.length > 0 ? `${dates[0]} to ${dates[dates.length-1]}` : 'no dates',
              recordCount: records.length,
              validCount: records.filter(d => d.calendarDate && (d.deepSleepSeconds || d.lightSleepSeconds || d.remSleepSeconds || d.sleepScores)).length
            });
          } catch (err) {
            reject(new Error(`Failed to parse ${file.name}`));
          }
        };
        reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
        reader.readAsText(file);
      });
    }))
    .then(results => {
      console.log('Files loaded:', results.map(r => ({
        file: r.fileName,
        range: r.dateRange,
        total: r.recordCount,
        valid: r.validCount
      })));
      
      // Flatten all new results - be more permissive with filtering
      // Only require calendarDate, other fields can be missing
      const allRawRecords = results.flatMap(r => r.data);
      const newRecords = allRawRecords.filter(d => {
        // Must have a calendar date
        if (!d.calendarDate) return false;
        // Must have at least some sleep data (any of these)
        const hasSleepData = d.deepSleepSeconds || d.lightSleepSeconds || d.remSleepSeconds || d.sleepScores;
        return hasSleepData;
      });
      
      // If merge mode, combine with existing data
      const allRecords = mergeMode ? [...sleepData, ...newRecords] : newRecords;
      
      // Deduplicate by calendarDate (keep last occurrence which is usually most complete)
      const byDate = new Map();
      allRecords.forEach(record => {
        byDate.set(record.calendarDate, record);
      });
      
      // Convert back to array and sort by date
      const deduped = Array.from(byDate.values()).sort((a, b) => 
        new Date(a.calendarDate) - new Date(b.calendarDate)
      );
      
      setSleepData(deduped);
      
      // Auto-generate name from date range
      const dates = deduped.map(d => d.calendarDate).sort();
      const dateRangeStr = dates.length > 0 ? `${dates[0]} to ${dates[dates.length-1]}` : 'No data';
      
      setCurrentFileName(dateRangeStr);
      
      // Auto-save to uploaded data
      if (deduped.length > 0) {
        autoSaveUpload(deduped, dateRangeStr);
      }
      
      const rejected = allRawRecords.length - newRecords.length;
      
      // Create per-file breakdown for debugging
      const fileBreakdown = results.map(r => `${r.fileName.slice(0,20)}...: ${r.validCount}/${r.recordCount} (${r.dateRange})`);
      
      setLoadInfo({
        filesLoaded: jsonFiles.length,
        fileNames: jsonFiles.map(f => f.name),
        totalRecords: allRecords.length,
        uniqueNights: deduped.length,
        duplicatesRemoved: allRecords.length - deduped.length,
        merged: mergeMode,
        rejected: rejected,
        dateRange: dateRangeStr,
        fileBreakdown: fileBreakdown
      });
      
      setMergeMode(false); // Reset merge mode after drop
    })
    .catch(err => setError(err.message));
  };

  const autoSaveUpload = (data, dateRangeStr) => {
    // Auto-save uploaded data with date range as name
    const saveName = dateRangeStr.replace(/ to /g, '_');
    
    const fileData = {
      name: saveName,
      savedAt: new Date().toISOString(),
      nightCount: data.length,
      dateRange: dateRangeStr
    };
    
    setSavedFiles(prev => {
      // Check if we already have this exact date range saved
      const existing = prev.filter(f => f.dateRange !== dateRangeStr);
      const updated = [...existing, fileData];
      
      localStorage.setItem('garmin_saved_files', JSON.stringify(updated));
      localStorage.setItem(`garmin_data_${saveName}`, JSON.stringify(data));
      
      return updated;
    });
  };

  const loadSavedFile = (fileName) => {
    const data = localStorage.getItem(`garmin_data_${fileName}`);
    if (data) {
      const parsed = JSON.parse(data);
      setSleepData(parsed);
      
      // Calculate date range
      const dates = parsed.map(d => d.calendarDate).sort();
      const dateRange = dates.length > 0 ? `${dates[0]} to ${dates[dates.length-1]}` : '';
      
      setCurrentFileName(dateRange);
      setLoadInfo({ filesLoaded: 1, uniqueNights: parsed.length, duplicatesRemoved: 0, dateRange: dateRange });
    }
  };

  const deleteSavedFile = (fileName) => {
    const updated = savedFiles.filter(f => f.name !== fileName);
    localStorage.setItem('garmin_saved_files', JSON.stringify(updated));
    localStorage.removeItem(`garmin_data_${fileName}`);
    setSavedFiles(updated);
  };

  // Filter data by date range
  const filteredData = useMemo(() => {
    if (!dateRange.start || !dateRange.end) return sleepData;
    return sleepData.filter(d => d.calendarDate >= dateRange.start && d.calendarDate <= dateRange.end);
  }, [sleepData, dateRange]);

  const calculateStats = (data) => {
    if (data.length === 0) return null;

    const validData = data.filter(d => d.calendarDate);
    
    const getValues = (accessor) => validData.map(accessor).filter(v => v != null && !isNaN(v));
    const avg = (arr) => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null;
    const min = (arr) => arr.length ? Math.min(...arr) : null;
    const max = (arr) => arr.length ? Math.max(...arr) : null;

    const sleepScores = getValues(d => d.sleepScores?.overallScore);
    const durations = getValues(d => {
      const total = (d.deepSleepSeconds || 0) + (d.lightSleepSeconds || 0) + (d.remSleepSeconds || 0) + (d.awakeSleepSeconds || 0);
      return total > 0 ? total / 3600 : null;
    });
    const remMinutes = getValues(d => d.remSleepSeconds ? d.remSleepSeconds / 60 : null);
    const deepMinutes = getValues(d => d.deepSleepSeconds ? d.deepSleepSeconds / 60 : null);
    const respAvg = getValues(d => d.averageRespiration);
    const respLow = getValues(d => d.lowestRespiration);
    const spo2Avg = getValues(d => d.spo2SleepSummary?.averageSPO2);
    const spo2Low = getValues(d => d.spo2SleepSummary?.lowestSPO2);
    const stress = getValues(d => d.avgSleepStress);

    const sorted = [...validData].sort((a, b) => new Date(a.calendarDate) - new Date(b.calendarDate));

    const timeSeries = sorted.map(d => ({
      date: d.calendarDate,
      shortDate: d.calendarDate.slice(5),
      score: d.sleepScores?.overallScore,
      duration: ((d.deepSleepSeconds || 0) + (d.lightSleepSeconds || 0) + (d.remSleepSeconds || 0) + (d.awakeSleepSeconds || 0)) / 3600,
      rem: d.remSleepSeconds ? d.remSleepSeconds / 60 : null,
      deep: d.deepSleepSeconds ? d.deepSleepSeconds / 60 : null,
      light: d.lightSleepSeconds ? d.lightSleepSeconds / 60 : null,
      respiration: d.averageRespiration,
      respLow: d.lowestRespiration,
      spo2: d.spo2SleepSummary?.averageSPO2,
      spo2Low: d.spo2SleepSummary?.lowestSPO2,
      stress: d.avgSleepStress
    }));

    const withRolling = timeSeries.map((d, i) => {
      const window = timeSeries.slice(Math.max(0, i - 6), i + 1);
      const remVals = window.map(w => w.rem).filter(v => v != null);
      const deepVals = window.map(w => w.deep).filter(v => v != null);
      const scoreVals = window.map(w => w.score).filter(v => v != null);
      const respVals = window.map(w => w.respiration).filter(v => v != null);
      return {
        ...d,
        remRolling: remVals.length ? remVals.reduce((a,b) => a+b, 0) / remVals.length : null,
        deepRolling: deepVals.length ? deepVals.reduce((a,b) => a+b, 0) / deepVals.length : null,
        scoreRolling: scoreVals.length ? scoreVals.reduce((a,b) => a+b, 0) / scoreVals.length : null,
        respRolling: respVals.length ? respVals.reduce((a,b) => a+b, 0) / respVals.length : null,
      };
    });

    return {
      totalNights: validData.length,
      sleepScore: { avg: avg(sleepScores), min: min(sleepScores), max: max(sleepScores) },
      duration: { avg: avg(durations), min: min(durations), max: max(durations) },
      rem: { avg: avg(remMinutes), min: min(remMinutes), max: max(remMinutes) },
      deep: { avg: avg(deepMinutes), min: min(deepMinutes), max: max(deepMinutes) },
      respiration: { avg: avg(respAvg), lowestAvg: avg(respLow), lowestMin: min(respLow) },
      spo2: { avg: avg(spo2Avg), lowestAvg: avg(spo2Low), lowestMin: min(spo2Low) },
      stress: { avg: avg(stress), min: min(stress), max: max(stress) },
      timeSeries: withRolling
    };
  };

  const stats = useMemo(() => calculateStats(filteredData), [filteredData]);

  // Aggregate data by week or month
  const aggregatedTimeSeries = useMemo(() => {
    if (!stats?.timeSeries) return [];
    
    if (viewMode === 'days') {
      // Ensure days are sorted chronologically (oldest first = left side of chart)
      return [...stats.timeSeries].sort((a, b) => new Date(a.date) - new Date(b.date));
    }
    
    const grouped = new Map();
    
    stats.timeSeries.forEach(day => {
      let key;
      const date = new Date(day.date + 'T00:00:00'); // Ensure consistent date parsing
      
      if (viewMode === 'weeks') {
        // Get Monday of the week
        const monday = new Date(date);
        const dayOfWeek = date.getDay();
        const diff = date.getDate() - dayOfWeek + (dayOfWeek === 0 ? -6 : 1);
        monday.setDate(diff);
        key = monday.toISOString().split('T')[0];
      } else if (viewMode === 'months') {
        key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
      }
      
      if (!grouped.has(key)) {
        grouped.set(key, []);
      }
      grouped.get(key).push(day);
    });
    
    // Calculate averages for each group
    const groupedData = Array.from(grouped.entries()).map(([key, days]) => {
      const avg = (arr, field) => {
        const vals = arr.map(d => d[field]).filter(v => v != null);
        return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
      };
      
      return {
        date: key,
        shortDate: viewMode === 'months' ? key : key.slice(5),
        label: viewMode === 'weeks' ? `Week of ${key}` : viewMode === 'months' ? key : key,
        nights: days.length,
        score: avg(days, 'score'),
        duration: avg(days, 'duration'),
        rem: avg(days, 'rem'),
        deep: avg(days, 'deep'),
        light: avg(days, 'light'),
        respiration: avg(days, 'respiration'),
        respLow: avg(days, 'respLow'),
        spo2: avg(days, 'spo2'),
        spo2Low: avg(days, 'spo2Low'),
        stress: avg(days, 'stress'),
      };
    });
    
    // Sort chronologically - oldest date first (appears on LEFT of chart)
    // For YYYY-MM format (months), append -01 to make valid date
    groupedData.sort((a, b) => {
      const dateA = new Date(a.date.length === 7 ? a.date + '-01' : a.date);
      const dateB = new Date(b.date.length === 7 ? b.date + '-01' : b.date);
      return dateA - dateB;
    });
    
    // Add rolling averages for trend lines (3-period for weeks/months)
    const windowSize = viewMode === 'days' ? 7 : 3;
    return groupedData.map((d, i) => {
      const window = groupedData.slice(Math.max(0, i - windowSize + 1), i + 1);
      const rollingAvg = (field) => {
        const vals = window.map(w => w[field]).filter(v => v != null);
        return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
      };
      return {
        ...d,
        remRolling: rollingAvg('rem'),
        deepRolling: rollingAvg('deep'),
        scoreRolling: rollingAvg('score'),
        respRolling: rollingAvg('respiration'),
        stressRolling: rollingAvg('stress'),
        spo2Rolling: rollingAvg('spo2'),
        spo2LowRolling: rollingAvg('spo2Low'),
      };
    });
  }, [stats?.timeSeries, viewMode]);

  // Comparison stats
  const comparisonStats = useMemo(() => {
    if (!compareMode) return null;
    
    const period1Data = sleepData.filter(d => d.calendarDate >= period1.start && d.calendarDate <= period1.end);
    const period2Data = sleepData.filter(d => d.calendarDate >= period2.start && d.calendarDate <= period2.end);
    
    return {
      period1: calculateStats(period1Data),
      period2: calculateStats(period2Data)
    };
  }, [compareMode, sleepData, period1, period2]);

  // Prior period stats for trend display in non-compare mode
  const priorPeriodStats = useMemo(() => {
    if (!dateRange.start || !dateRange.end || sleepData.length === 0) return null;
    
    const daysDiff = Math.round((new Date(dateRange.end) - new Date(dateRange.start)) / (1000 * 60 * 60 * 24));
    const priorEnd = new Date(dateRange.start);
    priorEnd.setDate(priorEnd.getDate() - 1);
    const priorStart = new Date(priorEnd);
    priorStart.setDate(priorStart.getDate() - daysDiff);
    
    const priorData = sleepData.filter(d => 
      d.calendarDate >= priorStart.toISOString().split('T')[0] && 
      d.calendarDate <= priorEnd.toISOString().split('T')[0]
    );
    
    if (priorData.length === 0) return null;
    
    return calculateStats(priorData);
  }, [dateRange, sleepData]);

  // Calculate trend within selected period (first half vs second half)
  const periodTrend = useMemo(() => {
    if (!stats?.timeSeries || stats.timeSeries.length < 4) return null;
    
    const mid = Math.floor(stats.timeSeries.length / 2);
    const firstHalf = stats.timeSeries.slice(0, mid);
    const secondHalf = stats.timeSeries.slice(mid);
    
    const avg = (arr, key) => {
      const vals = arr.map(d => d[key]).filter(v => v != null);
      return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    };
    
    return {
      sleepScore: { first: avg(firstHalf, 'score'), second: avg(secondHalf, 'score') },
      duration: { first: avg(firstHalf, 'duration'), second: avg(secondHalf, 'duration') },
      rem: { first: avg(firstHalf, 'rem'), second: avg(secondHalf, 'rem') },
      deep: { first: avg(firstHalf, 'deep'), second: avg(secondHalf, 'deep') },
      respiration: { first: avg(firstHalf, 'respiration'), second: avg(secondHalf, 'respiration') },
      spo2Low: { first: avg(firstHalf, 'spo2Low'), second: avg(secondHalf, 'spo2Low') },
      stress: { first: avg(firstHalf, 'stress'), second: avg(secondHalf, 'stress') },
    };
  }, [stats?.timeSeries]);

  const formatNum = (val, decimals = 1) => val != null ? val.toFixed(decimals) : '-';
  
  const formatDiff = (val1, val2, decimals = 1, invert = false) => {
    if (val1 == null || val2 == null) return '-';
    const diff = val2 - val1;
    const sign = diff > 0 ? '+' : '';
    const color = invert 
      ? (diff < 0 ? 'text-green-400' : diff > 0 ? 'text-red-400' : 'text-gray-400')
      : (diff > 0 ? 'text-green-400' : diff < 0 ? 'text-red-400' : 'text-gray-400');
    return <span className={color}>{sign}{diff.toFixed(decimals)}</span>;
  };

  const chartConfigs = {
    rem: { title: 'REM Sleep', dataKey: 'rem', rollingKey: 'remRolling', color: '#8b5cf6', unit: 'min', refLine: 90, refLabel: 'Target 90min', domain: ['auto', 'auto'] },
    deep: { title: 'Deep Sleep', dataKey: 'deep', rollingKey: 'deepRolling', color: '#3b82f6', unit: 'min', refLine: 60, refLabel: 'Min 60min', domain: ['auto', 'auto'] },
    score: { title: 'Sleep Score', dataKey: 'score', rollingKey: 'scoreRolling', color: '#10b981', unit: '', refLine: 80, refLabel: 'Good', domain: ['auto', 'auto'] },
    respiration: { title: 'Respiration Rate', dataKey: 'respiration', rollingKey: 'respRolling', color: '#f59e0b', unit: 'brpm', refLine: 14, refLabel: 'Normal', domain: ['auto', 'auto'] },
    stress: { title: 'Sleep Stress', dataKey: 'stress', rollingKey: 'stressRolling', color: '#ef4444', unit: '', refLine: 20, refLabel: 'Low', domain: ['auto', 'auto'] },
    spo2: { title: 'SpO2 (Lowest)', dataKey: 'spo2Low', rollingKey: 'spo2LowRolling', color: '#06b6d4', unit: '%', refLine: 92, refLabel: 'Concern <92%', domain: [85, 100] }
  };

  const currentChart = chartConfigs[activeChart];

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 p-4">
      <h1 className="text-2xl font-bold mb-4 text-blue-400">
        Garmin Sleep Analyzer
        <span className="text-xs font-normal text-gray-500 ml-2">v1.9.0</span>
      </h1>
      
      {/* Collapsible Upload Section */}
      {sleepData.length > 0 ? (
        <div className="mb-4">
          <button
            onClick={() => setUploadExpanded(!uploadExpanded)}
            className="flex items-center gap-2 text-sm text-gray-400 hover:text-gray-300 mb-2"
          >
            <span className={`transition-transform ${uploadExpanded ? 'rotate-90' : ''}`}>▶</span>
            <span>Data Management</span>
            <span className="text-xs text-gray-500">({sleepData.length} nights loaded)</span>
          </button>
          
          {uploadExpanded && (
            <div className="flex flex-wrap gap-3 bg-gray-800/50 rounded-lg p-3">
              {/* Drop Zone */}
              <div
                onDrop={handleDrop}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                className={`w-48 border-2 border-dashed rounded-lg p-3 text-center transition-colors ${
                  dragOver ? 'border-blue-400 bg-blue-900/20' : mergeMode ? 'border-green-500 bg-green-900/20' : 'border-gray-600 hover:border-gray-500'
                }`}
              >
                <p className="text-gray-400 text-xs">
                  {mergeMode ? '➕ Drop to ADD' : 'Drop JSON files'}
                </p>
                {loadInfo && (
                  <div className="text-xs mt-1">
                    <span className="text-blue-400">{loadInfo.uniqueNights} nights</span>
                    {loadInfo.rejected > 0 && <span className="text-red-400"> • {loadInfo.rejected} skipped</span>}
                  </div>
                )}
                {sleepData.length > 0 && (
                  <button
                    onClick={() => setMergeMode(!mergeMode)}
                    className={`mt-2 text-xs px-2 py-0.5 rounded ${
                      mergeMode ? 'bg-green-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                    }`}
                  >
                    {mergeMode ? 'Cancel' : '+ Add more'}
                  </button>
                )}
                {error && <p className="text-red-400 text-xs mt-1">{error}</p>}
              </div>

              {/* Saved Files */}
              <div className="bg-gray-800 rounded-lg p-3 flex-1 min-w-64">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-gray-400">Saved Datasets</span>
                  {savedFiles.length > 0 && (
                    <button 
                      onClick={() => {
                        savedFiles.forEach(f => localStorage.removeItem(`garmin_data_${f.name}`));
                        localStorage.removeItem('garmin_saved_files');
                        setSavedFiles([]);
                      }}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Clear all
                    </button>
                  )}
                </div>
                {savedFiles.length === 0 ? (
                  <p className="text-xs text-gray-500">No saved datasets</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {savedFiles.map(f => (
                      <div 
                        key={f.name} 
                        className={`flex items-center gap-2 text-xs rounded px-2 py-1 cursor-pointer ${
                          currentFileName === f.dateRange 
                            ? 'bg-blue-600 text-white' 
                            : 'bg-gray-700 hover:bg-gray-600'
                        }`}
                        onClick={() => loadSavedFile(f.name)}
                      >
                        <span title={f.name}>{f.dateRange}</span>
                        <span className="text-gray-400">({f.nightCount})</span>
                        <button 
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteSavedFile(f.name);
                          }}
                          className="text-red-400 hover:text-red-300 ml-1"
                        >
                          ×
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      ) : (
        /* Initial Upload State - Always Visible */
        <div className="flex flex-wrap gap-3 mb-4">
          {/* Drop Zone - narrower */}
          <div
            onDrop={handleDrop}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            className={`w-48 border-2 border-dashed rounded-lg p-3 text-center transition-colors ${
              dragOver ? 'border-blue-400 bg-blue-900/20' : 'border-gray-600 hover:border-gray-500'
            }`}
          >
            <p className="text-gray-400 text-xs">Drop JSON files</p>
            {error && <p className="text-red-400 text-xs mt-1">{error}</p>}
          </div>

          {/* Saved Files */}
          <div className="bg-gray-800 rounded-lg p-3 flex-1 min-w-64">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-400">Saved Datasets</span>
              {savedFiles.length > 0 && (
                <button 
                  onClick={() => {
                    savedFiles.forEach(f => localStorage.removeItem(`garmin_data_${f.name}`));
                    localStorage.removeItem('garmin_saved_files');
                    setSavedFiles([]);
                  }}
                  className="text-xs text-red-400 hover:text-red-300"
                >
                  Clear all
                </button>
              )}
            </div>
            {savedFiles.length === 0 ? (
              <p className="text-xs text-gray-500">No saved datasets - drop files to begin</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {savedFiles.map(f => (
                  <div 
                    key={f.name} 
                    className={`flex items-center gap-2 text-xs rounded px-2 py-1 cursor-pointer ${
                      currentFileName === f.dateRange 
                        ? 'bg-blue-600 text-white' 
                        : 'bg-gray-700 hover:bg-gray-600'
                    }`}
                    onClick={() => loadSavedFile(f.name)}
                  >
                    <span title={f.name}>{f.dateRange}</span>
                    <span className="text-gray-400">({f.nightCount})</span>
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        deleteSavedFile(f.name);
                      }}
                      className="text-red-400 hover:text-red-300 ml-1"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}



      {stats && availableDates.min && availableDates.max && (
        <div className="space-y-4">
          {/* Unified Date Picker Bar */}
          <div className="bg-gray-800 rounded-lg p-3">
            <div className="flex flex-wrap items-center gap-3">
              {/* View Mode Toggle */}
              <div className="flex bg-gray-700 rounded overflow-hidden">
                {['days', 'weeks', 'months'].map(mode => (
                  <button
                    key={mode}
                    onClick={() => setViewMode(mode)}
                    className={`px-3 py-1.5 text-xs capitalize ${
                      viewMode === mode ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-600'
                    }`}
                  >
                    {mode}
                  </button>
                ))}
              </div>

              {/* Main Date Range Button - Opens Picker */}
              <button
                onClick={() => setShowDatePicker(true)}
                className="flex items-center gap-2 bg-gray-700 hover:bg-gray-600 rounded px-3 py-1.5 text-sm"
              >
                <span className="text-blue-400">📅</span>
                <span>{dateRange.start}</span>
                <span className="text-gray-500">→</span>
                <span>{dateRange.end}</span>
                <span className="text-gray-400 text-xs">({stats.totalNights} nights)</span>
                <span className="text-gray-500">▼</span>
              </button>

              {/* Quick Presets - Always Visible */}
              <div className="flex items-center gap-1">
                {[
                  { label: '7d', days: 7 },
                  { label: '14d', days: 14 },
                  { label: '30d', days: 30 },
                  { label: '3mo', days: 90 },
                  { label: '6mo', days: 180 },
                  { label: '1y', days: 365 },
                ].map(preset => {
                  return (
                    <button
                      key={preset.label}
                      onClick={() => {
                        const end = new Date(availableDates.max);
                        const start = new Date(end);
                        start.setDate(start.getDate() - preset.days + 1);
                        const startStr = start.toISOString().split('T')[0];
                        setDateRange({ start: startStr, end: availableDates.max });
                        setActivePreset(preset.label);
                        // If in compare mode, update comparison periods too
                        if (compareMode) {
                          const p1End = new Date(start);
                          p1End.setDate(p1End.getDate() - 1);
                          const p1Start = new Date(p1End);
                          p1Start.setDate(p1Start.getDate() - preset.days + 1);
                          setPeriod1({ start: p1Start.toISOString().split('T')[0], end: p1End.toISOString().split('T')[0] });
                          setPeriod2({ start: startStr, end: availableDates.max });
                          setCompareType('previous');
                        }
                      }}
                      className={`px-2 py-1 text-xs rounded transition-colors ${
                        activePreset === preset.label ? 'bg-blue-600 text-white' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                      }`}
                    >
                      {preset.label}
                    </button>
                  );
                })}
                <button
                  onClick={() => {
                    setDateRange({ start: availableDates.min, end: availableDates.max });
                    setActivePreset('all');
                    // If in compare mode, split data in half for comparison
                    if (compareMode) {
                      const totalDays = Math.round((new Date(availableDates.max) - new Date(availableDates.min)) / (1000 * 60 * 60 * 24));
                      const midDate = new Date(availableDates.min);
                      midDate.setDate(midDate.getDate() + Math.floor(totalDays / 2));
                      const midStr = midDate.toISOString().split('T')[0];
                      const midMinus1 = new Date(midDate);
                      midMinus1.setDate(midMinus1.getDate() - 1);
                      setPeriod1({ start: availableDates.min, end: midMinus1.toISOString().split('T')[0] });
                      setPeriod2({ start: midStr, end: availableDates.max });
                      setCompareType('custom');
                    }
                  }}
                  className={`px-2 py-1 text-xs rounded transition-colors ${
                    activePreset === 'all' ? 'bg-blue-600 text-white' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                  }`}
                >
                  All
                </button>
              </div>

              {/* Navigation */}
              <div className="flex items-center gap-1 ml-auto">
                <button
                  onClick={() => {
                    const daysDiff = Math.round((new Date(dateRange.end) - new Date(dateRange.start)) / (1000 * 60 * 60 * 24));
                    const newEnd = new Date(dateRange.start);
                    newEnd.setDate(newEnd.getDate() - 1);
                    const newStart = new Date(newEnd);
                    newStart.setDate(newStart.getDate() - daysDiff);
                    if (newStart >= new Date(availableDates.min)) {
                      setDateRange({
                        start: newStart.toISOString().split('T')[0],
                        end: newEnd.toISOString().split('T')[0]
                      });
                      setActivePreset(null);
                    }
                  }}
                  className="p-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs"
                  title="Previous period"
                >
                  ◀◀
                </button>
                <button
                  onClick={() => {
                    const daysDiff = Math.round((new Date(dateRange.end) - new Date(dateRange.start)) / (1000 * 60 * 60 * 24)) + 1;
                    const newStart = new Date(dateRange.end);
                    newStart.setDate(newStart.getDate() + 1);
                    const newEnd = new Date(newStart);
                    newEnd.setDate(newEnd.getDate() + daysDiff - 1);
                    if (newEnd <= new Date(availableDates.max)) {
                      setDateRange({
                        start: newStart.toISOString().split('T')[0],
                        end: newEnd.toISOString().split('T')[0]
                      });
                      setActivePreset(null);
                    }
                  }}
                  className="p-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs"
                  title="Next period"
                >
                  ▶▶
                </button>
              </div>

              {/* Compare Toggle */}
              <button
                onClick={() => {
                  if (!compareMode) {
                    // Auto-set comparison to previous period
                    const daysDiff = Math.round((new Date(dateRange.end) - new Date(dateRange.start)) / (1000 * 60 * 60 * 24));
                    const p1End = new Date(dateRange.start);
                    p1End.setDate(p1End.getDate() - 1);
                    const p1Start = new Date(p1End);
                    p1Start.setDate(p1Start.getDate() - daysDiff);
                    
                    setPeriod1({ 
                      start: p1Start.toISOString().split('T')[0], 
                      end: p1End.toISOString().split('T')[0] 
                    });
                    setPeriod2({ start: dateRange.start, end: dateRange.end });
                    setCompareType('previous');
                  }
                  setCompareMode(!compareMode);
                }}
                className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                  compareMode 
                    ? 'bg-purple-600 text-white' 
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                }`}
              >
                {compareMode ? '✓ Comparing' : 'Compare'}
              </button>
            </div>

            {/* Compare Options - Visual Timeline Selector */}
            {compareMode && (
              <div className="mt-2 pt-2 border-t border-gray-700 space-y-3">
                {/* Quick presets row */}
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <span className="text-gray-500">Quick:</span>
                  
                  {[
                    { label: '7d', days: 7 },
                    { label: '30d', days: 30 },
                    { label: '90d', days: 90 },
                    { label: '6mo', days: 182 },
                    { label: '1y', days: 365 },
                  ].map(preset => (
                    <button
                      key={preset.label}
                      onClick={() => {
                        setCompareType(`${preset.days}d`);
                        const end = new Date(availableDates.max);
                        const start = new Date(end);
                        start.setDate(start.getDate() - preset.days + 1);
                        // Period A = current (most recent)
                        setPeriod2({ start: start.toISOString().split('T')[0], end: availableDates.max });
                        // Period B = prior period (auto-calculated)
                        const p1End = new Date(start);
                        p1End.setDate(p1End.getDate() - 1);
                        const p1Start = new Date(p1End);
                        p1Start.setDate(p1Start.getDate() - preset.days + 1);
                        setPeriod1({ start: p1Start.toISOString().split('T')[0], end: p1End.toISOString().split('T')[0] });
                        setDateRange({ start: start.toISOString().split('T')[0], end: availableDates.max });
                        setActivePreset(preset.label);
                      }}
                      className={`px-2 py-1 rounded transition-colors ${
                        compareType === `${preset.days}d` ? 'bg-purple-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                      }`}
                    >
                      {preset.label}
                    </button>
                  ))}
                  
                  <span className="text-gray-700 mx-1">|</span>
                  
                  <span className="text-gray-500">Compare to:</span>
                  <button
                    onClick={() => {
                      setCompareType('previous');
                      const daysDiff = Math.round((new Date(period2.end) - new Date(period2.start)) / (1000 * 60 * 60 * 24));
                      const p1End = new Date(period2.start);
                      p1End.setDate(p1End.getDate() - 1);
                      const p1Start = new Date(p1End);
                      p1Start.setDate(p1Start.getDate() - daysDiff);
                      setPeriod1({ start: p1Start.toISOString().split('T')[0], end: p1End.toISOString().split('T')[0] });
                    }}
                    className={`px-2 py-1 rounded transition-colors ${
                      compareType === 'previous' || compareType.endsWith('d') ? 'bg-purple-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                    }`}
                  >
                    Prior
                  </button>
                  {(() => {
                    // Check if YoY is possible - need data from a year ago
                    const yoyStartDate = new Date(period2.start);
                    yoyStartDate.setFullYear(yoyStartDate.getFullYear() - 1);
                    const yoyEndDate = new Date(period2.end);
                    yoyEndDate.setFullYear(yoyEndDate.getFullYear() - 1);
                    const hasYoyData = yoyStartDate >= new Date(availableDates.min) && yoyEndDate >= new Date(availableDates.min);
                    
                    return (
                      <button
                        onClick={() => {
                          if (!hasYoyData) return;
                          setCompareType('year');
                          setPeriod1({ start: yoyStartDate.toISOString().split('T')[0], end: yoyEndDate.toISOString().split('T')[0] });
                        }}
                        disabled={!hasYoyData}
                        className={`px-2 py-1 rounded transition-colors ${
                          !hasYoyData 
                            ? 'bg-gray-800 text-gray-600 cursor-not-allowed' 
                            : compareType === 'year' 
                              ? 'bg-purple-600 text-white' 
                              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                        }`}
                        title={!hasYoyData ? 'Not enough historical data for year-over-year comparison' : 'Compare to same period last year'}
                      >
                        YoY
                      </button>
                    );
                  })()}
                </div>

                {/* Timeline with drag-to-select */}
                <div className="bg-gray-800 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-2">Drag on timeline to select period • Comparison auto-calculated</div>
                  
                  {/* Timeline */}
                  <div 
                    className="relative h-12 bg-gray-700 rounded cursor-crosshair select-none"
                    onMouseDown={(e) => {
                      const rect = e.currentTarget.getBoundingClientRect();
                      const totalDays = Math.round((new Date(availableDates.max) - new Date(availableDates.min)) / (1000*60*60*24));
                      const dayIndex = Math.round(((e.clientX - rect.left) / rect.width) * totalDays);
                      const d = new Date(availableDates.min);
                      d.setDate(d.getDate() + dayIndex);
                      const date = d.toISOString().split('T')[0];
                      setDragPeriod({ dragging: true, startX: e.clientX, startDate: date, currentDate: date });
                    }}
                    onMouseMove={(e) => {
                      if (dragPeriod.dragging) {
                        const rect = e.currentTarget.getBoundingClientRect();
                        const totalDays = Math.round((new Date(availableDates.max) - new Date(availableDates.min)) / (1000*60*60*24));
                        const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                        const dayIndex = Math.round(pct * totalDays);
                        const d = new Date(availableDates.min);
                        d.setDate(d.getDate() + dayIndex);
                        const currentDate = d.toISOString().split('T')[0];
                        setDragPeriod(prev => ({ ...prev, currentDate }));
                      }
                    }}
                    onMouseUp={() => {
                      if (dragPeriod.dragging && dragPeriod.startDate && dragPeriod.currentDate) {
                        const dates = [dragPeriod.startDate, dragPeriod.currentDate].sort();
                        // Set Period A (current)
                        setPeriod2({ start: dates[0], end: dates[1] });
                        // Auto-calculate Period B (prior period)
                        const daysDiff = Math.round((new Date(dates[1]) - new Date(dates[0])) / (1000*60*60*24));
                        const p1End = new Date(dates[0]);
                        p1End.setDate(p1End.getDate() - 1);
                        const p1Start = new Date(p1End);
                        p1Start.setDate(p1Start.getDate() - daysDiff);
                        setPeriod1({ start: p1Start.toISOString().split('T')[0], end: p1End.toISOString().split('T')[0] });
                        setCompareType('previous');
                      }
                      setDragPeriod({ dragging: false, startX: 0, startDate: '', currentDate: '' });
                    }}
                    onMouseLeave={() => {
                      if (dragPeriod.dragging) {
                        setDragPeriod({ dragging: false, startX: 0, startDate: '', currentDate: '' });
                      }
                    }}
                  >
                    {/* Period B (comparison - gray) */}
                    {(() => {
                      const totalDays = Math.round((new Date(availableDates.max) - new Date(availableDates.min)) / (1000*60*60*24));
                      const p1StartDay = Math.round((new Date(period1.start) - new Date(availableDates.min)) / (1000*60*60*24));
                      const p1EndDay = Math.round((new Date(period1.end) - new Date(availableDates.min)) / (1000*60*60*24));
                      const p1StartPct = Math.max(0, (p1StartDay / totalDays) * 100);
                      const p1EndPct = Math.min(100, (p1EndDay / totalDays) * 100);
                      return (
                        <div 
                          className="absolute h-full bg-gray-500/60 rounded"
                          style={{ left: `${p1StartPct}%`, width: `${p1EndPct - p1StartPct}%` }}
                        />
                      );
                    })()}
                    
                    {/* Period A (current - blue) */}
                    {(() => {
                      const totalDays = Math.round((new Date(availableDates.max) - new Date(availableDates.min)) / (1000*60*60*24));
                      const p2StartDay = Math.round((new Date(period2.start) - new Date(availableDates.min)) / (1000*60*60*24));
                      const p2EndDay = Math.round((new Date(period2.end) - new Date(availableDates.min)) / (1000*60*60*24));
                      const p2StartPct = Math.max(0, (p2StartDay / totalDays) * 100);
                      const p2EndPct = Math.min(100, (p2EndDay / totalDays) * 100);
                      return (
                        <div 
                          className="absolute h-full bg-blue-500/70 rounded"
                          style={{ left: `${p2StartPct}%`, width: `${p2EndPct - p2StartPct}%` }}
                        />
                      );
                    })()}
                    
                    {/* Drag preview */}
                    {dragPeriod.dragging && dragPeriod.startDate && dragPeriod.currentDate && (() => {
                      const totalDays = Math.round((new Date(availableDates.max) - new Date(availableDates.min)) / (1000*60*60*24));
                      const dates = [dragPeriod.startDate, dragPeriod.currentDate].sort();
                      const startDay = Math.round((new Date(dates[0]) - new Date(availableDates.min)) / (1000*60*60*24));
                      const endDay = Math.round((new Date(dates[1]) - new Date(availableDates.min)) / (1000*60*60*24));
                      const startPct = (startDay / totalDays) * 100;
                      const endPct = (endDay / totalDays) * 100;
                      const dayCount = endDay - startDay + 1;
                      return (
                        <>
                          <div 
                            className="absolute h-full bg-blue-400/90 rounded ring-2 ring-blue-300"
                            style={{ left: `${startPct}%`, width: `${endPct - startPct}%` }}
                          />
                          <div 
                            className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-gray-900 px-2 py-1 rounded text-xs font-medium text-white whitespace-nowrap z-30"
                          >
                            {dates[0]} → {dates[1]} ({dayCount}d)
                          </div>
                        </>
                      );
                    })()}
                    
                    {/* Date labels */}
                    <div className="absolute bottom-1 left-2 text-[10px] text-gray-400">{availableDates.min}</div>
                    <div className="absolute bottom-1 right-2 text-[10px] text-gray-400">{availableDates.max}</div>
                  </div>

                  {/* Period summary */}
                  <div className="flex items-center justify-between mt-3 text-sm">
                    <div className="flex items-center gap-2">
                      <span className="w-3 h-3 rounded bg-gray-500"></span>
                      <span className="text-gray-400 font-medium">Comparison:</span>
                      <span className="text-gray-300">{period1.start} → {period1.end}</span>
                      <span className="text-gray-500 text-xs">
                        ({Math.round((new Date(period1.end) - new Date(period1.start)) / (1000*60*60*24)) + 1}d)
                      </span>
                    </div>
                    
                    <div className="flex items-center gap-2">
                      <span className="w-3 h-3 rounded bg-blue-500"></span>
                      <span className="text-blue-400 font-medium">Selected:</span>
                      <span className="text-gray-300">{period2.start} → {period2.end}</span>
                      <span className="text-gray-500 text-xs">
                        ({Math.round((new Date(period2.end) - new Date(period2.start)) / (1000*60*60*24)) + 1}d)
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Date Picker Modal */}
          {showDatePicker && (
            <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowDatePicker(false)}>
              <div className="bg-gray-800 rounded-lg shadow-2xl max-w-2xl w-full mx-4" onClick={e => e.stopPropagation()}>
                <div className="p-4">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold">Select Date Range</h3>
                    <button onClick={() => setShowDatePicker(false)} className="text-gray-400 hover:text-white text-xl">×</button>
                  </div>

                  {/* Quick Presets */}
                  <div className="flex flex-wrap gap-2 mb-4">
                    {[
                      { label: '7d', days: 7 },
                      { label: '14d', days: 14 },
                      { label: '30d', days: 30 },
                      { label: '3mo', days: 90 },
                      { label: '6mo', days: 182 },
                      { label: '1y', days: 365 },
                      { label: 'All', getValue: () => ({ start: availableDates.min, end: availableDates.max }), preset: 'all' },
                    ].map(item => (
                      <button
                        key={item.label}
                        onClick={() => {
                          if (item.getValue) {
                            setDateRange(item.getValue());
                          } else {
                            const end = new Date(availableDates.max);
                            const start = new Date(end);
                            start.setDate(start.getDate() - item.days + 1);
                            setDateRange({ start: start.toISOString().split('T')[0], end: availableDates.max });
                          }
                          setActivePreset(item.preset || item.label);
                          setShowDatePicker(false);
                        }}
                        className={`px-3 py-2 text-sm rounded transition-colors ${
                          activePreset === (item.preset || item.label) 
                            ? 'bg-blue-600 text-white' 
                            : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                        }`}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>

                  {/* Date Inputs */}
                  <div className="mb-4">
                    <div className="flex items-center gap-4">
                      <div className="flex-1">
                        <label className="block text-xs text-gray-400 mb-1">From</label>
                        <input
                          type="date"
                          value={dateRange.start}
                          min={availableDates.min}
                          max={dateRange.end}
                          onChange={(e) => {
                            setDateRange(prev => ({ ...prev, start: e.target.value }));
                            setActivePreset(null);
                          }}
                          className="w-full bg-gray-700 rounded px-3 py-2 text-sm border border-gray-600 focus:border-blue-500 focus:outline-none"
                        />
                      </div>
                      <span className="text-gray-500 mt-5">→</span>
                      <div className="flex-1">
                        <label className="block text-xs text-gray-400 mb-1">To</label>
                        <input
                          type="date"
                          value={dateRange.end}
                          min={dateRange.start}
                          max={availableDates.max}
                          onChange={(e) => {
                            setDateRange(prev => ({ ...prev, end: e.target.value }));
                            setActivePreset(null);
                          }}
                          className="w-full bg-gray-700 rounded px-3 py-2 text-sm border border-gray-600 focus:border-blue-500 focus:outline-none"
                        />
                      </div>
                      <div className="mt-5">
                        <span className="text-blue-400 font-medium text-sm">
                          {Math.round((new Date(dateRange.end) - new Date(dateRange.start)) / (1000*60*60*24)) + 1} days
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Apply Button */}
                  <div className="flex justify-end">
                    <button
                      onClick={() => setShowDatePicker(false)}
                      className="px-6 py-2 text-sm bg-blue-600 hover:bg-blue-700 rounded font-medium"
                    >
                      Apply
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Comparison Results - Modern Visual Cards */}
          {compareMode && comparisonStats?.period1 && comparisonStats?.period2 && (
            <div className="space-y-3">
              {/* Comparison Metric Cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <ComparisonCard 
                  title="Sleep Score"
                  value1={comparisonStats.period1.sleepScore?.avg}
                  value2={comparisonStats.period2.sleepScore?.avg}
                  format={v => formatNum(v, 0)}
                  unit=""
                  higherIsBetter={true}
                />
                <ComparisonCard 
                  title="Duration"
                  value1={comparisonStats.period1.duration?.avg}
                  value2={comparisonStats.period2.duration?.avg}
                  format={v => formatNum(v, 1)}
                  unit=" hrs"
                  higherIsBetter={true}
                />
                <ComparisonCard 
                  title="REM Sleep"
                  value1={comparisonStats.period1.rem?.avg}
                  value2={comparisonStats.period2.rem?.avg}
                  format={v => formatNum(v, 0)}
                  unit=" min"
                  higherIsBetter={true}
                />
                <ComparisonCard 
                  title="Deep Sleep"
                  value1={comparisonStats.period1.deep?.avg}
                  value2={comparisonStats.period2.deep?.avg}
                  format={v => formatNum(v, 0)}
                  unit=" min"
                  higherIsBetter={true}
                />
                <ComparisonCard 
                  title="Respiration"
                  value1={comparisonStats.period1.respiration?.avg}
                  value2={comparisonStats.period2.respiration?.avg}
                  format={v => formatNum(v, 1)}
                  unit=" brpm"
                  higherIsBetter={false}
                />
                <ComparisonCard 
                  title="Lowest Resp"
                  value1={comparisonStats.period1.respiration?.lowestAvg}
                  value2={comparisonStats.period2.respiration?.lowestAvg}
                  format={v => formatNum(v, 1)}
                  unit=" brpm"
                  higherIsBetter={false}
                />
                <ComparisonCard 
                  title="SpO2 (Lowest)"
                  value1={comparisonStats.period1.spo2?.lowestAvg}
                  value2={comparisonStats.period2.spo2?.lowestAvg}
                  format={v => formatNum(v, 1)}
                  unit="%"
                  higherIsBetter={true}
                />
                <ComparisonCard 
                  title="Stress"
                  value1={comparisonStats.period1.stress?.avg}
                  value2={comparisonStats.period2.stress?.avg}
                  format={v => formatNum(v, 1)}
                  unit=""
                  higherIsBetter={false}
                />
              </div>

              {/* Main Chart for Comparison - shows both periods */}
              <div className="bg-gray-800 rounded-lg p-4">
                <h2 className="text-lg font-semibold mb-3 text-blue-300">
                  {currentChart.title} Comparison
                </h2>
                <ResponsiveContainer width="100%" height={300}>
                  <ComposedChart data={aggregatedTimeSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis 
                      dataKey="shortDate" 
                      stroke="#9ca3af" 
                      tick={{ fontSize: 10 }} 
                      interval={viewMode === 'days' ? Math.floor(aggregatedTimeSeries.length / 10) : 0}
                    />
                    <YAxis stroke="#9ca3af" tick={{ fontSize: 11 }} domain={currentChart.domain} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#1f2937', border: 'none', borderRadius: '8px' }} 
                      labelStyle={{ color: '#9ca3af' }}
                      formatter={(value, name) => {
                        if (value == null) return ['-', name];
                        return [Math.round(value * 10) / 10, name.replace('Rolling', ' trend')];
                      }}
                    />
                    <ReferenceLine y={currentChart.refLine} stroke="#6b7280" strokeDasharray="5 5" />
                    <Bar dataKey={currentChart.dataKey} fill={currentChart.color} opacity={0.4} />
                    {currentChart.rollingKey && (
                      <Line type="monotone" dataKey={currentChart.rollingKey} stroke={currentChart.color} strokeWidth={2} dot={false} />
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Stats Grid - Only show when not in compare mode */}
          {!compareMode && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <StatCard 
                  title="Sleep Score" 
                  avg={formatNum(stats.sleepScore.avg, 0)} 
                  range={`${formatNum(stats.sleepScore.min, 0)} - ${formatNum(stats.sleepScore.max, 0)}`}
                  trend={periodTrend?.sleepScore}
                  priorValue={priorPeriodStats?.sleepScore?.avg}
                  higherIsBetter={true}
                />
                <StatCard 
                  title="Duration" 
                  avg={`${formatNum(stats.duration.avg)} hrs`} 
                  range={`${formatNum(stats.duration.min)} - ${formatNum(stats.duration.max)} hrs`}
                  trend={periodTrend?.duration}
                  priorValue={priorPeriodStats?.duration?.avg}
                  higherIsBetter={true}
                />
                <StatCard 
                  title="REM Sleep" 
                  avg={`${formatNum(stats.rem.avg)} min`} 
                  range={`${formatNum(stats.rem.min, 0)} - ${formatNum(stats.rem.max, 0)} min`}
                  trend={periodTrend?.rem}
                  priorValue={priorPeriodStats?.rem?.avg}
                  higherIsBetter={true}
                />
                <StatCard 
                  title="Deep Sleep" 
                  avg={`${formatNum(stats.deep.avg)} min`} 
                  range={`${formatNum(stats.deep.min, 0)} - ${formatNum(stats.deep.max, 0)} min`}
                  trend={periodTrend?.deep}
                  priorValue={priorPeriodStats?.deep?.avg}
                  higherIsBetter={true}
                />
                <StatCard 
                  title="Respiration" 
                  avg={`${formatNum(stats.respiration.avg)} brpm`} 
                  range={`Lowest avg: ${formatNum(stats.respiration.lowestAvg)} brpm`}
                  trend={periodTrend?.respiration}
                  priorValue={priorPeriodStats?.respiration?.avg}
                  higherIsBetter={false}
                />
                <StatCard 
                  title="SpO2 (Lowest)" 
                  avg={`${formatNum(stats.spo2.lowestAvg)}%`} 
                  range={`Low: ${formatNum(stats.spo2.lowestMin, 0)}% • Avg: ${formatNum(stats.spo2.avg)}%`}
                  trend={periodTrend?.spo2Low}
                  priorValue={priorPeriodStats?.spo2?.lowestAvg}
                  higherIsBetter={true}
                />
                <StatCard 
                  title="Stress" 
                  avg={formatNum(stats.stress.avg)} 
                  range={`${formatNum(stats.stress.min)} - ${formatNum(stats.stress.max)}`}
                  trend={periodTrend?.stress}
                  priorValue={priorPeriodStats?.stress?.avg}
                  higherIsBetter={false}
                />
                <StatCard title="HRV" avg="N/A" range="Not in export" dimmed />
              </div>

              {/* Chart Selector */}
              <div className="flex flex-wrap gap-2">
                {Object.entries(chartConfigs).map(([key, config]) => (
                  <button
                    key={key}
                    onClick={() => setActiveChart(key)}
                    className={`px-3 py-1 rounded text-sm transition-colors ${
                      activeChart === key 
                        ? 'bg-blue-600 text-white' 
                        : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                    }`}
                  >
                    {config.title}
                  </button>
                ))}
              </div>

              {/* Main Chart */}
              <div className="bg-gray-800 rounded-lg p-4 relative">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-lg font-semibold text-blue-300">
                    {currentChart.title} Trend 
                    <span className="text-sm font-normal text-gray-500 ml-2">
                      ({viewMode === 'days' ? 'Daily' : viewMode === 'weeks' ? 'Weekly avg' : 'Monthly avg'})
                    </span>
                  </h2>
                  <span className="text-xs text-gray-500">
                    {dateRange.start} → {dateRange.end} • {aggregatedTimeSeries.length} {viewMode}
                  </span>
                </div>
                <ResponsiveContainer width="100%" height={300}>
                  <ComposedChart 
                    data={aggregatedTimeSeries}
                    onMouseDown={(e) => {
                      if (e?.activeLabel) {
                        setSelectStart(e.activeLabel);
                        setIsSelecting(true);
                        setSelectionStats(null);
                      }
                    }}
                    onMouseMove={(e) => {
                      if (isSelecting && e?.activeLabel) {
                        setSelectEnd(e.activeLabel);
                      }
                    }}
                    onMouseUp={() => {
                      if (isSelecting && selectStart && selectEnd && selectStart !== selectEnd) {
                        // Find the actual dates from the short dates
                        const startItem = aggregatedTimeSeries.find(d => d.shortDate === selectStart);
                        const endItem = aggregatedTimeSeries.find(d => d.shortDate === selectEnd);
                        if (startItem && endItem) {
                          const dates = [startItem.date, endItem.date].sort();
                          // Get data in selection
                          const selectedData = aggregatedTimeSeries.filter(d => d.date >= dates[0] && d.date <= dates[1]);
                          if (selectedData.length > 0) {
                            const avg = (arr, key) => {
                              const vals = arr.map(d => d[key]).filter(v => v != null);
                              return vals.length ? vals.reduce((a,b) => a+b, 0) / vals.length : null;
                            };
                            const min = (arr, key) => {
                              const vals = arr.map(d => d[key]).filter(v => v != null);
                              return vals.length ? Math.min(...vals) : null;
                            };
                            const max = (arr, key) => {
                              const vals = arr.map(d => d[key]).filter(v => v != null);
                              return vals.length ? Math.max(...vals) : null;
                            };
                            // Calculate trend (first half vs second half)
                            const mid = Math.floor(selectedData.length / 2);
                            const firstHalf = selectedData.slice(0, mid);
                            const secondHalf = selectedData.slice(mid);
                            const firstAvg = avg(firstHalf, currentChart.dataKey);
                            const secondAvg = avg(secondHalf, currentChart.dataKey);
                            const trend = firstAvg && secondAvg ? ((secondAvg - firstAvg) / firstAvg * 100) : 0;
                            
                            setSelectionStats({
                              startDate: dates[0],
                              endDate: dates[1],
                              count: selectedData.length,
                              metric: currentChart.title,
                              avg: avg(selectedData, currentChart.dataKey),
                              min: min(selectedData, currentChart.dataKey),
                              max: max(selectedData, currentChart.dataKey),
                              trend: trend,
                              nights: selectedData.reduce((sum, d) => sum + (d.nights || 1), 0)
                            });
                          }
                        }
                      }
                      setIsSelecting(false);
                      setSelectStart(null);
                      setSelectEnd(null);
                    }}
                    onMouseLeave={() => {
                      if (isSelecting) {
                        setIsSelecting(false);
                        setSelectStart(null);
                        setSelectEnd(null);
                      }
                    }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis 
                      dataKey="shortDate" 
                      stroke="#9ca3af" 
                      tick={{ fontSize: 10 }} 
                      interval={viewMode === 'days' ? Math.floor(aggregatedTimeSeries.length / 10) : 0}
                      angle={viewMode !== 'days' ? -45 : 0}
                      textAnchor={viewMode !== 'days' ? 'end' : 'middle'}
                      height={viewMode !== 'days' ? 60 : 30}
                    />
                    <YAxis stroke="#9ca3af" tick={{ fontSize: 11 }} domain={currentChart.domain} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#1f2937', border: 'none', borderRadius: '8px' }} 
                      labelStyle={{ color: '#9ca3af' }}
                      formatter={(value, name) => {
                        if (value == null) return ['-', name];
                        const rounded = name.includes('Rolling') || name.includes('avg') 
                          ? value.toFixed(1) 
                          : Math.round(value);
                        return [rounded, name.replace('Rolling', ' trend')];
                      }}
                      labelFormatter={(label, payload) => {
                        if (payload?.[0]?.payload) {
                          const item = payload[0].payload;
                          if (viewMode === 'weeks') return `Week of ${item.date} (${item.nights} nights)`;
                          if (viewMode === 'months') return `${item.date} (${item.nights} nights)`;
                          return `${item.date}`;
                        }
                        return label;
                      }}
                    />
                    {isSelecting && selectStart && selectEnd && (
                      <ReferenceArea x1={selectStart} x2={selectEnd} strokeOpacity={0.3} fill="#3b82f6" fillOpacity={0.3} />
                    )}
                    <ReferenceLine y={currentChart.refLine} stroke="#6b7280" strokeDasharray="5 5" label={{ value: currentChart.refLabel, fill: '#6b7280', fontSize: 10 }} />
                    <Bar dataKey={currentChart.dataKey} fill={currentChart.color} opacity={0.4} />
                    {currentChart.rollingKey && (
                      <Line type="monotone" dataKey={currentChart.rollingKey} stroke={currentChart.color} strokeWidth={2} dot={false} name={viewMode === 'days' ? '7-day avg' : '3-period avg'} />
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
                <p className="text-xs text-gray-500 text-center mt-1">
                  Drag on chart to analyze a selection
                </p>
                
                {/* Selection Stats Popup */}
                {selectionStats && (
                  <div className="absolute top-16 right-4 bg-gray-900 border border-gray-600 rounded-lg p-4 shadow-xl z-10 w-72">
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="text-sm font-semibold text-blue-300">Selection Analysis</h4>
                      <button 
                        onClick={() => setSelectionStats(null)}
                        className="text-gray-400 hover:text-white text-lg leading-none"
                      >
                        ×
                      </button>
                    </div>
                    
                    <div className="text-xs text-gray-400 mb-3">
                      {selectionStats.startDate} → {selectionStats.endDate}
                      <span className="ml-2 text-gray-500">
                        ({selectionStats.count} {viewMode} • {selectionStats.nights} nights)
                      </span>
                    </div>
                    
                    <div className="space-y-2 mb-4">
                      <div className="flex justify-between">
                        <span className="text-gray-400">{selectionStats.metric} Avg:</span>
                        <span className="font-medium">{selectionStats.avg?.toFixed(1) || '-'}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-400">Range:</span>
                        <span className="text-gray-300">
                          {selectionStats.min?.toFixed(1) || '-'} - {selectionStats.max?.toFixed(1) || '-'}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-400">Trend (1st→2nd half):</span>
                        <span className={`font-medium ${
                          selectionStats.trend > 0 ? 'text-green-400' : 
                          selectionStats.trend < 0 ? 'text-red-400' : 'text-gray-400'
                        }`}>
                          {selectionStats.trend > 0 ? '↑' : selectionStats.trend < 0 ? '↓' : '→'}
                          {Math.abs(selectionStats.trend).toFixed(1)}%
                        </span>
                      </div>
                    </div>
                    
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          setDateRange({ start: selectionStats.startDate, end: selectionStats.endDate });
                          setActivePreset(null);
                          setSelectionStats(null);
                        }}
                        className="flex-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-xs font-medium"
                      >
                        Zoom to Selection
                      </button>
                      <button
                        onClick={() => {
                          // Set up comparison: selection vs previous period of same length
                          const daysDiff = Math.round((new Date(selectionStats.endDate) - new Date(selectionStats.startDate)) / (1000 * 60 * 60 * 24));
                          const p1End = new Date(selectionStats.startDate);
                          p1End.setDate(p1End.getDate() - 1);
                          const p1Start = new Date(p1End);
                          p1Start.setDate(p1Start.getDate() - daysDiff);
                          
                          setPeriod1({ 
                            start: p1Start.toISOString().split('T')[0], 
                            end: p1End.toISOString().split('T')[0] 
                          });
                          setPeriod2({ 
                            start: selectionStats.startDate, 
                            end: selectionStats.endDate 
                          });
                          setCompareMode(true);
                          setCompareType('custom');
                          setActivePreset(null);
                          setSelectionStats(null);
                        }}
                        className="flex-1 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded text-xs font-medium"
                      >
                        Compare to Prior
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* Sleep Architecture */}
              <div className="bg-gray-800 rounded-lg p-4">
                <h2 className="text-lg font-semibold mb-3 text-blue-300">
                  Sleep Architecture
                  <span className="text-sm font-normal text-gray-500 ml-2">
                    ({viewMode === 'days' ? 'Daily' : viewMode === 'weeks' ? 'Weekly avg' : 'Monthly avg'})
                  </span>
                </h2>
                <ResponsiveContainer width="100%" height={250}>
                  <ComposedChart data={aggregatedTimeSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis 
                      dataKey="shortDate" 
                      stroke="#9ca3af" 
                      tick={{ fontSize: 10 }} 
                      interval={viewMode === 'days' ? Math.floor(aggregatedTimeSeries.length / 10) : 0}
                      angle={viewMode !== 'days' ? -45 : 0}
                      textAnchor={viewMode !== 'days' ? 'end' : 'middle'}
                      height={viewMode !== 'days' ? 60 : 30}
                    />
                    <YAxis stroke="#9ca3af" tick={{ fontSize: 11 }} label={{ value: 'Minutes', angle: -90, position: 'insideLeft', fill: '#9ca3af', fontSize: 11 }} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#1f2937', border: 'none', borderRadius: '8px' }} 
                      formatter={(value) => [`${value?.toFixed(0)} min`]}
                      labelFormatter={(label, payload) => {
                        if (payload?.[0]?.payload?.nights && viewMode !== 'days') {
                          return `${label} (${payload[0].payload.nights} nights)`;
                        }
                        return label;
                      }}
                    />
                    <Bar dataKey="deep" stackId="a" fill="#3b82f6" name="Deep" />
                    <Bar dataKey="rem" stackId="a" fill="#8b5cf6" name="REM" />
                    <Bar dataKey="light" stackId="a" fill="#6b7280" name="Light" />
                  </ComposedChart>
                </ResponsiveContainer>
                <div className="flex gap-4 justify-center mt-2 text-xs">
                  <span className="flex items-center gap-1"><span className="w-3 h-3 bg-blue-500 rounded"></span> Deep</span>
                  <span className="flex items-center gap-1"><span className="w-3 h-3 bg-purple-500 rounded"></span> REM</span>
                  <span className="flex items-center gap-1"><span className="w-3 h-3 bg-gray-500 rounded"></span> Light</span>
                </div>
              </div>

              {/* Respiration Detail */}
              <div className="bg-gray-800 rounded-lg p-4">
                <h2 className="text-lg font-semibold mb-3 text-blue-300">Respiration (Avg vs Lowest)</h2>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={aggregatedTimeSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis 
                      dataKey="shortDate" 
                      stroke="#9ca3af" 
                      tick={{ fontSize: 10 }} 
                      interval={viewMode === 'days' ? Math.floor(aggregatedTimeSeries.length / 10) : 0}
                    />
                    <YAxis stroke="#9ca3af" tick={{ fontSize: 11 }} domain={[4, 20]} />
                    <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: 'none', borderRadius: '8px' }} formatter={(value) => [value != null ? `${value.toFixed(1)} brpm` : '-']} />
                    <ReferenceLine y={12} stroke="#22c55e" strokeDasharray="5 5" label={{ value: 'Healthy low', fill: '#22c55e', fontSize: 10 }} />
                    <Line type="monotone" dataKey="respiration" stroke="#f59e0b" strokeWidth={2} dot={false} name="Average" />
                    <Line type="monotone" dataKey="respLow" stroke="#ef4444" strokeWidth={1.5} dot={false} name="Lowest" />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              {/* SpO2 Detail */}
              <div className="bg-gray-800 rounded-lg p-4">
                <h2 className="text-lg font-semibold mb-3 text-blue-300">SpO2 (Avg vs Lowest)</h2>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={aggregatedTimeSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis 
                      dataKey="shortDate" 
                      stroke="#9ca3af" 
                      tick={{ fontSize: 10 }} 
                      interval={viewMode === 'days' ? Math.floor(aggregatedTimeSeries.length / 10) : 0}
                    />
                    <YAxis stroke="#9ca3af" tick={{ fontSize: 11 }} domain={[85, 100]} />
                    <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: 'none', borderRadius: '8px' }} formatter={(value) => [value != null ? `${value.toFixed(1)}%` : '-']} />
                    <ReferenceLine y={95} stroke="#22c55e" strokeDasharray="5 5" label={{ value: 'Normal', fill: '#22c55e', fontSize: 10 }} />
                    <ReferenceLine y={88} stroke="#ef4444" strokeDasharray="5 5" label={{ value: 'Concern', fill: '#ef4444', fontSize: 10 }} />
                    <Line type="monotone" dataKey="spo2" stroke="#06b6d4" strokeWidth={2} dot={false} name="Average SpO2" />
                    <Line type="monotone" dataKey="spo2Low" stroke="#f97316" strokeWidth={1.5} dot={false} name="Lowest SpO2" />
                  </LineChart>
                </ResponsiveContainer>
                <div className="flex gap-4 justify-center mt-2 text-xs">
                  <span className="flex items-center gap-1"><span className="w-3 h-3 bg-cyan-500 rounded"></span> Average</span>
                  <span className="flex items-center gap-1"><span className="w-3 h-3 bg-orange-500 rounded"></span> Lowest</span>
                </div>
              </div>

              {/* Recent Data Table */}
              <div className="bg-gray-800 rounded-lg p-4 overflow-x-auto">
                <h2 className="text-lg font-semibold mb-3 text-blue-300">
                  {viewMode === 'days' ? 'Recent Nights (Last 14)' : 
                   viewMode === 'weeks' ? 'Weekly Summary' : 'Monthly Summary'}
                </h2>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-gray-400 border-b border-gray-700">
                      <th className="text-left py-2 px-2">{viewMode === 'days' ? 'Date' : 'Period'}</th>
                      {viewMode !== 'days' && <th className="text-right py-2 px-2">Nights</th>}
                      <th className="text-right py-2 px-2">Score</th>
                      <th className="text-right py-2 px-2">Dur</th>
                      <th className="text-right py-2 px-2">REM</th>
                      <th className="text-right py-2 px-2">Deep</th>
                      <th className="text-right py-2 px-2">Resp</th>
                      <th className="text-right py-2 px-2">SpO2</th>
                      <th className="text-right py-2 px-2">Stress</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...(viewMode === 'days' ? aggregatedTimeSeries.slice(-14) : aggregatedTimeSeries)].reverse().map((item) => (
                      <tr key={item.date} className="border-b border-gray-700/50 hover:bg-gray-700/30">
                        <td className="py-2 px-2">{item.date}</td>
                        {viewMode !== 'days' && <td className="text-right py-2 px-2 text-gray-400">{item.nights}</td>}
                        <td className="text-right py-2 px-2">{formatNum(item.score, 0)}</td>
                        <td className="text-right py-2 px-2">{formatNum(item.duration)}h</td>
                        <td className={`text-right py-2 px-2 ${item.rem < 60 ? 'text-red-400' : item.rem > 90 ? 'text-green-400' : ''}`}>
                          {formatNum(item.rem, 0)}m
                        </td>
                        <td className={`text-right py-2 px-2 ${item.deep < 60 ? 'text-yellow-400' : item.deep > 90 ? 'text-green-400' : ''}`}>
                          {formatNum(item.deep, 0)}m
                        </td>
                        <td className="text-right py-2 px-2">{formatNum(item.respiration)}</td>
                        <td className="text-right py-2 px-2">{formatNum(item.spo2)}%</td>
                        <td className={`text-right py-2 px-2 ${item.stress > 25 ? 'text-yellow-400' : ''}`}>
                          {formatNum(item.stress)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Key Observations */}
              <div className="bg-gray-800 rounded-lg p-4">
                <h2 className="text-lg font-semibold mb-3 text-blue-300">Key Observations</h2>
                <div className="space-y-2 text-sm">
                  {stats.rem.avg < 70 && <p className="text-yellow-400">⚠ REM average ({formatNum(stats.rem.avg)} min) below optimal (90+ min)</p>}
                  {stats.respiration.lowestAvg > 10 && <p className="text-yellow-400">⚠ Lowest respiration elevated (avg {formatNum(stats.respiration.lowestAvg)} brpm)</p>}
                  {stats.spo2.lowestMin < 88 && <p className="text-yellow-400">⚠ SpO2 dipped below 88% on some nights</p>}
                  {stats.stress.avg > 20 && <p className="text-yellow-400">⚠ Sleep stress elevated (avg {formatNum(stats.stress.avg)})</p>}
                  {stats.rem.max > 100 && <p className="text-green-400">✓ Capable of excellent REM (max {formatNum(stats.rem.max, 0)} min)</p>}
                  {stats.deep.avg > 70 && <p className="text-green-400">✓ Strong deep sleep ({formatNum(stats.deep.avg)} min avg)</p>}
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function StatCard({ title, avg, range, dimmed, trend, priorValue, higherIsBetter = true }) {
  // Calculate trend direction and color
  let trendElement = null;
  if (trend?.first != null && trend?.second != null) {
    const diff = trend.second - trend.first;
    const pct = trend.first !== 0 ? ((diff / trend.first) * 100) : 0;
    const isUp = diff > 0;
    const isGood = higherIsBetter ? isUp : !isUp;
    const noChange = Math.abs(pct) < 1;
    
    if (!noChange) {
      trendElement = (
        <span className={`text-[10px] ${isGood ? 'text-green-500' : 'text-red-500'}`}>
          {isUp ? '↗' : '↘'} {Math.abs(pct).toFixed(0)}%
        </span>
      );
    }
  }
  
  // Calculate vs prior period
  let priorElement = null;
  if (priorValue != null && avg != null) {
    // Extract numeric value from avg string (e.g., "7.2 hrs" -> 7.2)
    const currentNum = parseFloat(avg);
    if (!isNaN(currentNum) && !isNaN(priorValue)) {
      const diff = currentNum - priorValue;
      const pct = priorValue !== 0 ? ((diff / priorValue) * 100) : 0;
      const isUp = diff > 0;
      const isGood = higherIsBetter ? isUp : !isUp;
      const noChange = Math.abs(pct) < 1;
      
      if (!noChange) {
        priorElement = (
          <span className={`text-[10px] ${isGood ? 'text-green-500/70' : 'text-red-500/70'}`}>
            vs prior: {isUp ? '+' : ''}{pct.toFixed(0)}%
          </span>
        );
      }
    }
  }
  
  return (
    <div className={`bg-gray-800 rounded-lg p-3 ${dimmed ? 'opacity-50' : ''}`}>
      <div className="flex items-center justify-between">
        <h3 className="text-xs text-gray-400 mb-1">{title}</h3>
        {trendElement}
      </div>
      <p className="text-lg font-semibold">{avg}</p>
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">{range}</p>
        {priorElement}
      </div>
    </div>
  );
}

function ComparisonCard({ title, value1, value2, format, unit, higherIsBetter }) {
  // value1 = Comparison period (older), value2 = Selected period (recent)
  const v1 = value1 ?? 0;
  const v2 = value2 ?? 0;
  const diff = v2 - v1;
  const absDiff = Math.abs(diff);
  const pctChange = v1 !== 0 ? ((diff / v1) * 100) : 0;
  
  // Direction of change
  const increased = diff > 0;
  const noChange = absDiff < 0.1;
  
  // Is this change good or bad?
  const isGood = higherIsBetter ? increased : !increased;
  
  // Change indicator color (green=good, red=bad)
  const changeColor = noChange ? 'text-gray-500' : isGood ? 'text-green-400' : 'text-red-400';
  
  // Selected (current) value - colored by outcome: green if improved, red if worsened
  const selectedColor = noChange ? 'text-gray-300' : isGood ? 'text-green-400' : 'text-red-400';
  
  return (
    <div className="bg-gray-800 rounded-lg p-3">
      <h3 className="text-xs font-medium text-gray-400 mb-2">{title}</h3>
      
      {/* Layout: comparison (neutral) → change → selected (colored by outcome) */}
      <div className="flex items-center justify-between gap-2">
        {/* Comparison value - neutral gray */}
        <span className="text-lg font-bold text-gray-400">{format(v1)}{unit}</span>
        
        {/* Change indicator */}
        <span className={`text-xs font-medium ${changeColor} whitespace-nowrap`}>
          {noChange ? '—' : (
            <>
              {increased ? '↑' : '↓'}{Math.abs(pctChange).toFixed(0)}%
            </>
          )}
        </span>
        
        {/* Selected value - colored green/red based on whether change is good/bad */}
        <span className={`text-lg font-bold ${selectedColor}`}>{format(v2)}{unit}</span>
      </div>
    </div>
  );
}
