import { describe, it, expect } from 'vitest'
import { answerQuestion, enrichPredictions } from '../explain'
import type { FileSummary, Prediction } from '@/types'

describe('explain.ts', () => {
  const mockPredictions: Prediction[] = [
    {
      fileId: 'file1.txt',
      pAccess: 0.85,
      candidateTiers: ['HOT'],
      banditChoice: 'HOT',
      predictionTimestamp: '2024-01-01T00:00:00Z',
      topReasons: [
        { feature: 'days_since_last_access', contribution: '+1.3717' },
        { feature: 'access_count_7d', contribution: '+0.8234' },
        { feature: 'file_age_days', contribution: '-0.2345' }
      ]
    },
    {
      fileId: 'file2.pdf',
      pAccess: 0.45,
      candidateTiers: ['WARM', 'COLD'],
      banditChoice: 'WARM',
      predictionTimestamp: '2024-01-01T00:00:00Z',
      topReasons: [
        { feature: 'file_type', contribution: '+0.5123' },
        { feature: 'access_count_30d', contribution: '-0.3456' }
      ]
    },
    {
      fileId: 'file3.doc',
      pAccess: 0.15,
      candidateTiers: ['COLD'],
      banditChoice: 'COLD',
      predictionTimestamp: '2024-01-01T00:00:00Z',
      topReasons: null
    },
    {
      fileId: 'pinned_file.xlsx',
      pAccess: 0.5,
      candidateTiers: [],
      banditChoice: null,
      predictionTimestamp: '2024-01-01T00:00:00Z',
      topReasons: []
    }
  ]

  const fileList: FileSummary[] = [
    {
      fileId: '7b12cdef-1234', filename: 'résumé-测试.txt', size: 10,
      lastModified: '2024-01-01T00:00:00Z', storageClass: 'STANDARD_IA',
      uploadedAt: null, protected: false, pinnedAt: null,
    },
  ]

  describe('enriched file matching', () => {
    const enriched = enrichPredictions([
      { ...mockPredictions[0], fileId: '7b12cdef-1234', predictionTimestamp: '2024-01-01T00:00:00Z' },
    ], fileList)

    it('matches a full filename with and without its extension', () => {
      expect(answerQuestion('Why was résumé-测试.txt moved?', enriched).text).toContain('résumé-测试.txt')
      expect(answerQuestion('Why was résumé-测试 moved?', enriched).text).toContain('85%')
    })

    it('matches Unicode names after accent-insensitive normalization', () => {
      expect(answerQuestion('Why was resume moved?', enriched).text).toContain('85%')
      expect(answerQuestion('Why was résumé moved?', enriched).text).toContain('85%')
    })

    it('matches the first eight characters of the file ID', () => {
      expect(answerQuestion('Why was 7b12cdef moved?', enriched).text).toContain('85%')
    })

    it('lists available prediction filenames when a requested file is not found', () => {
      const result = answerQuestion('Why was missing.txt moved?', enriched)
      expect(result.text).toContain(`I couldn't find "missing.txt" among your files with predictions.`)
      expect(result.text).toContain('Files I can explain: résumé-测试.txt')
    })

    it('uses only the latest prediction for a file', () => {
      const latest = { ...mockPredictions[0], fileId: '7b12cdef-1234', pAccess: 0.12, predictionTimestamp: '2024-03-01T00:00:00Z' }
      const rows = enrichPredictions([
        { ...mockPredictions[0], fileId: '7b12cdef-1234', predictionTimestamp: '2024-01-01T00:00:00Z' },
        latest,
      ], fileList)
      expect(rows).toHaveLength(1)
      expect(answerQuestion('Why was résumé moved?', rows).text).toContain('12%')
    })
  })

  describe('intent: why_tier', () => {
    it('explains tier recommendation for a specific file', () => {
      const result = answerQuestion('Why was file1.txt moved to HOT?', mockPredictions)
      expect(result.text).toContain('file1.txt')
      expect(result.text).toContain('85%')
      expect(result.text).toContain('HOT')
      expect(result.text).toContain('days since last access')
    })

    it('uses single prediction when no file specified', () => {
      const singlePrediction = [mockPredictions[0]]
      const result = answerQuestion('Why was it moved to HOT?', singlePrediction)
      expect(result.text).toContain('85%')
      expect(result.text).toContain('HOT')
    })

    it('asks for clarification when multiple predictions and no file specified', () => {
      const result = answerQuestion('Why was it moved?', mockPredictions)
      expect(result.text).toContain('Which file?')
      expect(result.text).toContain('Options:')
    })

    it('handles bandit choice between candidates', () => {
      const result = answerQuestion('Why was file2.pdf recommended?', mockPredictions)
      expect(result.text).toContain('WARM or COLD')
      expect(result.text).toContain('bandit')
      expect(result.text).toContain('past feedback')
    })

    it('handles empty topReasons', () => {
      const result = answerQuestion('Why was file3.doc moved?', mockPredictions)
      expect(result.text).toContain('Per-feature reasons are not stored')
    })

    it('handles pinned files', () => {
      const result = answerQuestion('Why was pinned_file.xlsx moved?', mockPredictions)
      expect(result.text).toContain('no automatic tier change')
    })
  })

  describe('intent: top_drivers', () => {
    it('lists top drivers for a file', () => {
      const result = answerQuestion('What are the top drivers for file1.txt?', mockPredictions)
      expect(result.text).toContain('days since last access')
      expect(result.text).toContain('accesses in the last 7 days')
      expect(result.text).toContain('SHAP values')
    })

    it('handles positive and negative contributions', () => {
      const result = answerQuestion('Explain file1.txt', mockPredictions)
      expect(result.text).toContain('pushes toward')
      expect(result.text).toContain('pushes away')
    })

    it('handles empty topReasons', () => {
      const result = answerQuestion('What are the reasons for file3.doc?', mockPredictions)
      expect(result.text).toContain('Per-feature reasons are not stored')
    })

    it('explains what SHAP values are', () => {
      const result = answerQuestion('What are the factors for file2.pdf?', mockPredictions)
      expect(result.text).toContain('SHAP values')
    })
  })

  describe('intent: pinned', () => {
    it('explains pinned file behavior', () => {
      const result = answerQuestion('Is pinned_file.xlsx pinned?', mockPredictions)
      expect(result.text).toContain('pinned')
      expect(result.text).toContain('never automatically moved')
    })

    it('explains unpinned file behavior', () => {
      const result = answerQuestion('Is file1.txt pinned?', mockPredictions)
      expect(result.text).toContain('not pinned')
      expect(result.text).toContain('automatic tiering')
    })
  })

  describe('intent: what_is_p_access', () => {
    it('explains p_access', () => {
      const result = answerQuestion('What is p_access?', mockPredictions)
      expect(result.text).toContain('chance')
      expect(result.text).toContain('7 days')
      expect(result.text).toContain('ranking score')
    })

    it('explains probability', () => {
      const result = answerQuestion('What does the probability mean?', mockPredictions)
      expect(result.text).toContain('ranking score')
    })
  })

  describe('intent: summary', () => {
    it('provides summary counts', () => {
      const result = answerQuestion('How many files are in each tier?', mockPredictions)
      expect(result.text).toContain('4 files')
      expect(result.text).toContain('probability band')
    })

    it('provides overview', () => {
      const result = answerQuestion('Give me a summary', mockPredictions)
      expect(result.text).toContain('4 files')
    })

    it('handles empty predictions', () => {
      const result = answerQuestion('Summary', [])
      expect(result.text).toContain('No predictions')
    })
  })

  describe('intent: most_likely', () => {
    it('lists most likely files', () => {
      const result = answerQuestion('Which files are most likely to be accessed?', mockPredictions)
      expect(result.text).toContain('most likely')
      expect(result.text).toContain('file1.txt')
    })

    it('handles empty predictions', () => {
      const result = answerQuestion('Most likely', [])
      expect(result.text).toContain('No predictions')
    })
  })

  describe('intent: least_likely', () => {
    it('lists least likely files', () => {
      const result = answerQuestion('Which files are least likely to be accessed?', mockPredictions)
      expect(result.text).toContain('least likely')
      expect(result.text).toContain('file3.doc')
    })

    it('handles "coldest" keyword', () => {
      const result = answerQuestion('Which files are coldest?', mockPredictions)
      expect(result.text).toContain('least likely')
    })
  })

  describe('intent: compare', () => {
    it('compares two files', () => {
      const result = answerQuestion('Compare file1.txt and file2.pdf', mockPredictions)
      expect(result.text).toContain('file1.txt')
      expect(result.text).toContain('file2.pdf')
      expect(result.text).toContain('85%')
      expect(result.text).toContain('45%')
    })

    it('asks for two files when only one mentioned', () => {
      const result = answerQuestion('Compare file1.txt', mockPredictions)
      expect(result.text).toContain('two file names')
    })
  })

  describe('intent: help', () => {
    it('provides help', () => {
      const result = answerQuestion('Help', mockPredictions)
      expect(result.text).toContain('answer questions')
      expect(result.text).toContain('Why was')
    })

    it('responds to "what can you do"', () => {
      const result = answerQuestion('What can you do?', mockPredictions)
      expect(result.text).toContain('answer questions')
    })
  })

  describe('file name matching', () => {
    it('matches exact file name', () => {
      const result = answerQuestion('Why was file1.txt moved?', mockPredictions)
      expect(result.text).toContain('file1.txt')
    })

    it('matches partial file name without extension', () => {
      const result = answerQuestion('Why was file1 moved?', mockPredictions)
      expect(result.text).toContain('85%')
    })

    it('matches case-insensitive', () => {
      const result = answerQuestion('Why was FILE1.TXT moved?', mockPredictions)
      expect(result.text).toContain('85%')
    })

    it('handles unknown file name', () => {
      const result = answerQuestion('Why was unknown_file.txt moved?', mockPredictions)
      expect(result.text).toContain("couldn't find")
    })
  })

  describe('band boundaries', () => {
    it('correctly identifies HOT band (>= 0.8)', () => {
      const result = answerQuestion('Why was file1.txt moved?', mockPredictions)
      expect(result.text).toContain('HOT band')
    })

    it('correctly identifies WARM band (0.4-0.6)', () => {
      const result = answerQuestion('Why was file2.pdf moved?', mockPredictions)
      expect(result.text).toContain('WARM band')
    })

    it('correctly identifies COLD band (< 0.2)', () => {
      const result = answerQuestion('Why was file3.doc moved?', mockPredictions)
      expect(result.text).toContain('COLD band')
    })
  })

  describe('sign parsing', () => {
    it('parses positive contributions', () => {
      const result = answerQuestion('What are the drivers for file1.txt?', mockPredictions)
      expect(result.text).toContain('+1.3717')
      expect(result.text).toContain('pushes toward')
    })

    it('parses negative contributions', () => {
      const result = answerQuestion('What are the drivers for file1.txt?', mockPredictions)
      expect(result.text).toContain('-0.2345')
      expect(result.text).toContain('pushes away')
    })

    it('never describes as percentages', () => {
      const result = answerQuestion('What are the drivers for file1.txt?', mockPredictions)
      expect(result.text).not.toMatch(/%.*contribution|contribution.*%/i)
    })
  })

  describe('fallback', () => {
    it('provides fallback for unrecognized questions', () => {
      const result = answerQuestion('What is the meaning of life?', mockPredictions)
      expect(result.text).toContain("didn't understand")
      expect(result.text).toContain('Try asking')
    })
  })

  describe('friendly feature names', () => {
    it('uses friendly names for known features', () => {
      const result = answerQuestion('What are the drivers for file1.txt?', mockPredictions)
      expect(result.text).toContain('days since last access')
      expect(result.text).toContain('accesses in the last 7 days')
    })

    it('falls back to raw name with spaces for unknown features', () => {
      const predictionsWithUnknown: Prediction[] = [
        {
          fileId: 'test.txt',
          pAccess: 0.5,
          candidateTiers: ['WARM'],
          banditChoice: 'WARM',
          predictionTimestamp: '2024-01-01T00:00:00Z',
          topReasons: [{ feature: ' unknown_feature_name ', contribution: '+0.5' }]
        }
      ]
      const result = answerQuestion('What are the drivers for test.txt?', predictionsWithUnknown)
      expect(result.text).toContain('unknown feature name')
    })
  })
})
