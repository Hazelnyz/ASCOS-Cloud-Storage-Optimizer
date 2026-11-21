import { tierFromStorageClass, type FileSummary, type Prediction, type StorageTier } from '@/types'
import { dedupePredictions } from '@/lib/predictions'

export interface EnrichedPrediction extends Prediction {
  filename: string | null
  currentTier: StorageTier | null
  protected: boolean | null
  fileListUnavailable: boolean
}

export function enrichPredictions(
  predictions: Prediction[],
  files: FileSummary[] | null,
  fileListUnavailable = false,
): EnrichedPrediction[] {
  const fileMap = new Map((files ?? []).map((file) => [file.fileId, file]))
  return dedupePredictions(predictions).map((prediction) => {
    const file = prediction.fileId ? fileMap.get(prediction.fileId) : undefined
    return {
      ...prediction,
      filename: file?.filename ?? null,
      currentTier: file ? tierFromStorageClass(file.storageClass) : null,
      protected: file?.protected ?? null,
      fileListUnavailable,
    }
  })
}

interface AnswerResult {
  text: string
}

// Friendly name map for features
const FEATURE_FRIENDLY_NAMES: Record<string, string> = {
  days_since_last_access: 'days since last access',
  access_count_7d: 'accesses in the last 7 days',
  access_count_30d: 'accesses in the last 30 days',
  file_age_days: 'file age in days',
  file_type: 'file type',
  current_storage_tier: 'current storage tier',
  file_size_bytes: 'file size',
  extension: 'file extension',
}

function friendlyFeatureName(feature: string): string {
  return FEATURE_FRIENDLY_NAMES[feature] || feature.trim().replace(/_/g, ' ')
}

function normalizeText(text: string): string {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
}

type ExplainablePrediction = Prediction & Partial<Pick<EnrichedPrediction, 'filename' | 'currentTier' | 'protected' | 'fileListUnavailable'>>

function predictionName(prediction: ExplainablePrediction): string {
  return prediction.filename || prediction.fileId || 'unknown'
}

function fileOptions(predictions: ExplainablePrediction[]): string {
  return predictions.slice(0, 8).map(predictionName).join(', ')
}

const NON_FILE_WORDS = new Set([
  'a', 'an', 'and', 'are', 'can', 'do', 'file', 'files', 'for', 'from', 'how', 'i', 'is', 'it',
  'me', 'moved', 'my', 'of', 'on', 'or', 'please', 'recommend', 'show', 'tell', 'the', 'tier',
  'tiers', 'to', 'was', 'what', 'when', 'where', 'which', 'who', 'why', 'with', 'hot', 'warm', 'cold',
])

function matchingScore(query: string, prediction: ExplainablePrediction): number {
  const normalizedQuery = normalizeText(query)
  if (!normalizedQuery) return 0
  const fileId = prediction.fileId || ''
  const name = prediction.filename || fileId
  const nameWithoutExt = name.replace(/\.[^.\\/]+$/, '')
  const fileIdWithoutExt = fileId.replace(/\.[^.\\/]+$/, '')
  const idPrefix = fileId.slice(0, 8)
  const alternatives = [nameWithoutExt, fileIdWithoutExt, idPrefix]
    .map(normalizeText)
    .filter(Boolean)

  if (idPrefix.length === 8 && normalizedQuery.split(' ').includes(normalizeText(idPrefix))) return 4

  let bestScore = 0
  for (const alternative of alternatives) {
    if (normalizedQuery === alternative) bestScore = Math.max(bestScore, 4)
    else if (new RegExp(`(^| )${alternative.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}($| )`).test(normalizedQuery) || alternative === normalizedQuery) bestScore = Math.max(bestScore, 2)
    else if (normalizedQuery.split(' ').some((token) => token.length >= 3 && !NON_FILE_WORDS.has(token) && alternative.split(' ').includes(token))) bestScore = Math.max(bestScore, 1)
  }
  return bestScore
}

function findPredictionByFileName(predictions: ExplainablePrediction[], fileName: string): ExplainablePrediction | null {
  return [...predictions]
    .map((prediction) => ({ prediction, score: matchingScore(fileName, prediction) }))
    .filter((match) => match.score > 0)
    .sort((a, b) => b.score - a.score)[0]?.prediction ?? null
}

function parseContribution(contribution: string): number {
  const parsed = parseFloat(contribution)
  return isNaN(parsed) ? 0 : parsed
}

function getBand(pAccess: number): string {
  if (pAccess >= 0.8) return 'HOT'
  if (pAccess >= 0.6) return 'HOT/WARM'
  if (pAccess >= 0.4) return 'WARM'
  if (pAccess >= 0.2) return 'WARM/COLD'
  return 'COLD'
}

function formatPAccess(pAccess: number): string {
  return `${Math.round(pAccess * 100)}%`
}

function extractFileNames(text: string, predictions: ExplainablePrediction[]): string[] {
  const found = predictions
    .filter((prediction) => matchingScore(text, prediction) > 0)
    .map(predictionName)
  const explicitNames = text.match(/[\p{L}\p{N}][\p{L}\p{N}_.-]*\.[\p{L}\p{N}]{1,10}/gu) || []
  for (const name of explicitNames) {
    if (!found.some((fileName) => normalizeText(fileName) === normalizeText(name))) found.push(name)
  }
  const idPrefixes = text.match(/\b[\da-fA-F]{8}\b/g) || []
  for (const prefix of idPrefixes) {
    if (!found.includes(prefix)) found.push(prefix)
  }
  return found
}

function notFoundMessage(fileName: string, predictions: ExplainablePrediction[]): string {
  return `I couldn't find "${fileName}" among your files with predictions. Files I can explain: ${fileOptions(predictions)}.`
}

function appendFileListNotice(text: string, predictions: ExplainablePrediction[]): string {
  return predictions.some((prediction) => prediction.fileListUnavailable)
    ? `${text} File names could not be loaded, so I'm using file IDs.`
    : text
}

function intentWhyTier(predictions: ExplainablePrediction[], fileNames: string[]): AnswerResult {
  if (fileNames.length === 0) {
    if (predictions.length === 1) {
      fileNames = [predictions[0].fileId || '']
    } else {
      const options = fileOptions(predictions)
      return { text: `Which file? Options: ${options}` }
    }
  }
  
  const pred = findPredictionByFileName(predictions, fileNames[0])
  if (!pred) {
    return { text: appendFileListNotice(notFoundMessage(fileNames[0], predictions), predictions) }
  }
  
  const pAccess = pred.pAccess ?? 0
  const band = getBand(pAccess)
  const pAccessPercent = formatPAccess(pAccess)
  const candidates = pred.candidateTiers.join(' or ')
  const choice = pred.banditChoice || 'none'

  if (pred.candidateTiers.length === 0 && !pred.banditChoice) {
    return { text: appendFileListNotice(`${predictionName(pred)} is pinned, so there is no automatic tier change.`, predictions) }
  }

  let answer = `${predictionName(pred)} has a p_access score of ${pAccessPercent}, which places it in the ${band} band. `
  answer += `The model considered ${candidates} as candidate tier(s), and the recommendation is ${choice}. `
  
  if (pred.candidateTiers.length > 1 && pred.banditChoice) {
    answer += `The bandit chose between tiers using past feedback from similar files. `
    answer += `No feedback has been collected yet, so it's using its initial preference. `
  }
  
  if (pred.topReasons && pred.topReasons.length > 0) {
    answer += `The top factors influencing this prediction are: `
    const top3 = pred.topReasons.slice(0, 3)
    const reasons = top3.map(r => {
      const name = friendlyFeatureName(r.feature)
      const value = parseContribution(r.contribution)
      const direction = value > 0 ? 'pushes toward "will be accessed"' : 'pushes away'
      return `${name} (${r.contribution}, ${direction})`
    }).join(', ')
    answer += reasons + '.'
  } else {
    answer += `Per-feature reasons are not stored for this prediction (generated before explanations were enabled).`
  }
  
  return { text: appendFileListNotice(answer, predictions) }
}

function intentTopDrivers(predictions: ExplainablePrediction[], fileNames: string[]): AnswerResult {
  if (fileNames.length === 0) {
    if (predictions.length === 1) {
      fileNames = [predictions[0].fileId || '']
    } else {
      const options = fileOptions(predictions)
      return { text: `Which file? Options: ${options}` }
    }
  }
  
  const pred = findPredictionByFileName(predictions, fileNames[0])
  if (!pred) {
    return { text: appendFileListNotice(notFoundMessage(fileNames[0], predictions), predictions) }
  }
  
  if (!pred.topReasons || pred.topReasons.length === 0) {
    return { text: appendFileListNotice(`Per-feature reasons are not stored for this prediction (generated before explanations were enabled).`, predictions) }
  }
  
  let answer = `The top drivers for this file are: `
  const reasons = pred.topReasons.map(r => {
    const name = friendlyFeatureName(r.feature)
    const value = parseContribution(r.contribution)
    const direction = value > 0 ? 'pushes toward "will be accessed"' : 'pushes away'
    return `${name} (${r.contribution}, ${direction})`
  }).join(', ')
  answer += reasons + '. '
  answer += `These are SHAP values, which measure how much each feature contributed to the prediction relative to the average prediction.`
  
  return { text: appendFileListNotice(answer, predictions) }
}

function intentPinned(predictions: ExplainablePrediction[], fileNames: string[]): AnswerResult {
  if (fileNames.length === 0) {
    if (predictions.length === 1) {
      fileNames = [predictions[0].fileId || '']
    } else {
      const options = fileOptions(predictions)
      return { text: `Which file? Options: ${options}` }
    }
  }
  
  const pred = findPredictionByFileName(predictions, fileNames[0])
  if (!pred) {
    return { text: appendFileListNotice(notFoundMessage(fileNames[0], predictions), predictions) }
  }
  
  const isPinned = pred.candidateTiers.length === 0 && !pred.banditChoice
  
  if (isPinned) {
    return { text: appendFileListNotice(`${predictionName(pred)} is pinned, so there is no automatic tier change. Pinned files are never automatically moved by the tiering policy. If a pinned file is in COLD storage, it will be restored to HOT. You can unpin it to allow automatic tiering.`, predictions) }
  }
  
  return { text: appendFileListNotice(`${predictionName(pred)} is not pinned. It will be subject to automatic tiering based on its access probability.`, predictions) }
}

function intentWhatIsPAccess(predictions: ExplainablePrediction[], fileNames: string[]): AnswerResult {
  if (fileNames.length > 0) {
    const pred = findPredictionByFileName(predictions, fileNames[0])
    if (!pred) return { text: appendFileListNotice(notFoundMessage(fileNames[0], predictions), predictions) }
    return { text: appendFileListNotice(`${predictionName(pred)} has a p_access score of ${formatPAccess(pred.pAccess ?? 0)}. It is the model's score for the chance that the file will be accessed within 7 days.`, predictions) }
  }
  return { text: `p_access is the model's score for the chance that a file will be accessed within 7 days. It's a ranking score used to compare files, not a guaranteed probability. Higher scores indicate files more likely to be accessed soon.` }
}

function intentSummary(predictions: Prediction[]): AnswerResult {
  if (predictions.length === 0) {
    return { text: `No predictions available to summarize.` }
  }
  
  const tierCounts: Record<string, number> = {}
  const bandCounts: Record<string, number> = { high: 0, medium: 0, low: 0 }
  
  for (const pred of predictions) {
    const pAccess = pred.pAccess ?? 0
    const band = pAccess >= 0.7 ? 'high' : pAccess >= 0.3 ? 'medium' : 'low'
    bandCounts[band]++
    
    if (pred.banditChoice) {
      tierCounts[pred.banditChoice] = (tierCounts[pred.banditChoice] || 0) + 1
    }
  }
  
  let answer = `You have ${predictions.length} files with predictions. `
  answer += `By probability band: ${bandCounts.high} high (>=70%), ${bandCounts.medium} medium (30-70%), ${bandCounts.low} low (<30%). `
  
  if (Object.keys(tierCounts).length > 0) {
    const tierSummary = Object.entries(tierCounts).map(([tier, count]) => `${count} ${tier}`).join(', ')
    answer += `By recommended tier: ${tierSummary}.`
  }
  
  return { text: answer }
}

function intentMostLikely(predictions: Prediction[]): AnswerResult {
  if (predictions.length === 0) {
    return { text: `No predictions available.` }
  }
  
  const sorted = [...predictions].filter(p => p.pAccess !== null).sort((a, b) => (b.pAccess ?? 0) - (a.pAccess ?? 0))
  const top3 = sorted.slice(0, 3)
  
  if (top3.length === 0) {
    return { text: `No predictions with valid p_access scores.` }
  }
  
  let answer = `The files most likely to be accessed are: `
  const items = top3.map(p => `${p.fileId || 'unknown'} (${formatPAccess(p.pAccess ?? 0)})`).join(', ')
  answer += items + '.'
  
  return { text: answer }
}

function intentLeastLikely(predictions: Prediction[]): AnswerResult {
  if (predictions.length === 0) {
    return { text: `No predictions available.` }
  }
  
  const sorted = [...predictions].filter(p => p.pAccess !== null).sort((a, b) => (a.pAccess ?? 0) - (b.pAccess ?? 0))
  const top3 = sorted.slice(0, 3)
  
  if (top3.length === 0) {
    return { text: `No predictions with valid p_access scores.` }
  }
  
  let answer = `The files least likely to be accessed are: `
  const items = top3.map(p => `${p.fileId || 'unknown'} (${formatPAccess(p.pAccess ?? 0)})`).join(', ')
  answer += items + '.'
  
  return { text: answer }
}

function intentCompare(predictions: Prediction[], fileNames: string[]): AnswerResult {
  if (fileNames.length < 2) {
    return { text: `To compare files, mention two file names in your question.` }
  }
  
  const pred1 = findPredictionByFileName(predictions, fileNames[0])
  const pred2 = findPredictionByFileName(predictions, fileNames[1])
  
  if (!pred1 || !pred2) {
    return { text: `I couldn't find both files. Please check the file names.` }
  }
  
  const pAccess1 = pred1.pAccess ?? 0
  const pAccess2 = pred2.pAccess ?? 0
  
  let answer = `${pred1.fileId} has a p_access of ${formatPAccess(pAccess1)} (${getBand(pAccess1)} band), `
  answer += `while ${pred2.fileId} has ${formatPAccess(pAccess2)} (${getBand(pAccess2)} band). `
  
  if (pAccess1 > pAccess2) {
    answer += `${pred1.fileId} is more likely to be accessed.`
  } else if (pAccess2 > pAccess1) {
    answer += `${pred2.fileId} is more likely to be accessed.`
  } else {
    answer += `They have equal access probabilities.`
  }
  
  return { text: answer }
}

function intentHelp(): AnswerResult {
  return { text: `I can answer questions about your file predictions. Try asking: "Why was file.txt moved to HOT?", "What are the top drivers for file.pdf?", "What is p_access?", "Which files are most likely to be accessed?", "How many files are in each tier?", or "Compare file1.txt and file2.pdf".` }
}

export function answerQuestion(text: string, predictions: ExplainablePrediction[]): AnswerResult {
  const normalized = normalizeText(text)
  const fileNames = extractFileNames(text, predictions)
  const has = (term: string) => new RegExp(`(^|[^\\p{L}\\p{N}])${normalizeText(term)}($|[^\\p{L}\\p{N}])`, 'u').test(normalized)

  if (has('help') || normalized.includes('what can you do')) {
    return intentHelp()
  }

  if (predictions.length === 0) {
    return { text: `No predictions available yet.` }
  }

  if (has('summary') || has('overview') || normalized.includes('how many') || has('count') || (has('tiers') && !has('why'))) {
    return intentSummary(predictions)
  }
  if (has('compare') || has('versus') || has('vs')) return intentCompare(predictions, fileNames)
  if (normalized.includes('most likely') || has('highest')) return intentMostLikely(predictions)
  if (has('least') || has('lowest') || has('coldest')) return intentLeastLikely(predictions)
  if (normalized.includes('p access') || has('score') || has('probability') || has('mean')) {
    return intentWhatIsPAccess(predictions, fileNames)
  }
  
  // Intent detection (ordered, first match wins)
  if (has('pin') || has('pinned') || has('protected') || normalized.includes('frequently used') || normalized.includes('wont move')) {
    return intentPinned(predictions, fileNames)
  }

  if (has('reason') || has('reasons') || has('factor') || has('factors') || has('driver') || has('drivers') || has('shap') || has('explain') || has('because')) {
    return intentTopDrivers(predictions, fileNames)
  }

  if (has('why') || has('recommend') || has('tier') || has('moved') || has('hot') || has('warm') || has('cold')) {
    return intentWhyTier(predictions, fileNames)
  }
  
  // Fallback
  return { text: `I didn't understand that question. Try asking: "Why was file.txt moved to HOT?", "What are the top drivers for file.pdf?", "What is p_access?", "Which files are most likely to be accessed?", or "How many files are in each tier?"` }
}

const OLLAMA_POLICY_FACTS = [
  'Policy bands: p_access >= 0.8 recommends HOT; 0.6-0.8 considers HOT/WARM; 0.4-0.6 recommends WARM; 0.2-0.4 considers WARM/COLD; <0.2 recommends COLD.',
  'Pinned files are never moved automatically.',
  'SHAP values are model log-odds contributions, not percentages; positive values push toward "will be accessed".',
  'p_access is a ranking score, not a guaranteed probability.',
  'Automatic tier execution is not enabled.',
  'The model is trained on synthetic data, and predictions come from a batch job.',
].join('\n')

/** Build the only file and policy context allowed to leave the browser for Ollama. */
export function buildAssistantContext(question: string, predictions: EnrichedPrediction[]): string {
  const namedFiles = extractFileNames(question, predictions)
  const match = namedFiles.map((name) => findPredictionByFileName(predictions, name)).find((row) => row !== null) ?? null
  const focused = match ? predictions.find((prediction) => prediction.fileId === match.fileId) ?? null : null
  const listed = predictions.slice(0, 30)
  if (focused && !listed.includes(focused)) listed[listed.length === 30 ? 29 : listed.length] = focused
  const files = listed.map((prediction) => ({
    filename: prediction.filename,
    fileId: prediction.fileId,
    currentTier: prediction.currentTier,
    p_access_score: prediction.pAccess,
    policy_band: prediction.pAccess === null ? null : getBand(prediction.pAccess),
    candidateTiers: prediction.candidateTiers,
    recommendedTier: prediction.banditChoice,
    pinned: prediction.protected === true || (prediction.candidateTiers.length === 0 && !prediction.banditChoice),
    topShapReasons: (prediction.topReasons ?? []).slice(0, 3).map((reason) => ({
      feature: friendlyFeatureName(reason.feature),
      signedValue: reason.contribution,
    })),
  }))
  return JSON.stringify({
    policyFacts: OLLAMA_POLICY_FACTS,
    files,
    ...(focused ? { focusedFile: focused.fileId, referenceAnswer: answerQuestion(question, predictions).text } : {}),
  }, null, 2)
}
