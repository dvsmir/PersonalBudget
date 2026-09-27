import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

const en = {
  nav: {
    dashboard: 'Dashboard', year: 'Year', transactions: 'Transactions', import: 'Import', budget: 'Budget',
    wealth: 'Wealth', accounts: 'Accounts', debts: 'Debts', assets: 'Assets & investments', earmarks: 'Earmarks',
    projects: 'Projects', settings: 'Settings',
  },
  common: {
    add: 'Add', save: 'Save', cancel: 'Cancel', delete: 'Delete', edit: 'Edit', close: 'Close', search: 'Search',
    loading: 'Loading…', none: 'None', total: 'Total', all: 'All', date: 'Date', amount: 'Amount', account: 'Account',
    category: 'Category', subcategory: 'Subcategory', description: 'Description', notes: 'Notes', project: 'Project',
    kind: 'Kind', currency: 'Currency', name: 'Name', type: 'Type', status: 'Status', from: 'From', to: 'To',
    month: 'Month', income: 'Income', expenses: 'Costs', balance: 'Balance', saved: 'Saved', error: 'Error',
    reference: 'EUR', native: '€ + ₽', logout: 'Log out', table: 'Table', chart: 'Chart', apply: 'Apply',
    archive: 'Archive', value: 'Value', actions: 'Actions', yes: 'Yes', no: 'No', retry: 'Retry',
    nothing: 'Nothing here yet',
  },
  kinds: {
    expense: 'Expense', income: 'Income', transfer: 'Transfer', debt_payment: 'Debt payment', debt_drawdown: 'Drawdown',
    investment: 'Investment', asset_purchase: 'Asset purchase', earmark: 'Earmark', adjustment: 'Adjustment', mixed: 'Mixed',
  },
  costType: { fixed: 'Fixed', variable: 'Variable', one_time: 'One-time' },
  login: { title: 'Sign in', email: 'E-mail', password: 'Password', totp: 'Authenticator code', submit: 'Sign in' },
  dash: {
    costsByCategory: 'Costs by category', costsByType: 'Costs by type', incomeByCategory: 'Income by category',
    budget: 'Plan vs actual', balances: 'Account balances', netWorth: 'Net worth', bridge: 'Change this month',
    cashFlow: 'Cash flow', vsPrev: 'vs last month', vsAvg: 'vs 12-mo avg', available: 'Available funds',
    alerts: 'Needs attention', reviewImports: '{{count}} import rows waiting for review',
    estimatedFx: 'Some amounts use an estimated exchange rate', principal: 'Debt principal repaid',
    toInvest: 'Into investments', noData: 'No transactions this month yet',
    funds: 'Funds', investments: 'Investments', assets: 'Assets', debts: 'Debts',
    bridgeParts: {
      income: 'Income', expenses: 'Costs', adjustments: 'Adjustments', conversion_cost: 'Conversion cost',
      asset_revaluation: 'Asset revaluation', investment_gain: 'Investment gain', debt_corrections: 'Debt corrections',
      fx_revaluation_and_rounding: 'FX revaluation',
    },
  },
  year: { months: 'Months', categories: 'Categories', avg: 'avg / month', heatmap: 'Costs by category and month', funds: 'Funds (end)' },
  txn: {
    new: 'New transaction', editTitle: 'Edit transaction', split: 'Split', addSplit: 'Add line', remaining: 'Remaining',
    fromAccount: 'From account', toAccount: 'To account', amountOut: 'Amount out', amountIn: 'Amount in',
    impliedRate: 'Implied rate', marketRate: 'Market rate', debt: 'Debt', interest: 'Interest', principal: 'Principal',
    suggest: 'Suggest split', saveAndNew: 'Save & add another', deleted: 'Transaction deleted',
    earmark: 'Earmark', allocate: 'Allocate', release: 'Release', security: 'Security', units: 'Units', price: 'Price',
    fees: 'Fees', buy: 'Buy', sell: 'Sell', filters: 'Filters', uncategorised: 'Uncategorised only',
    bulk: '{{count}} selected', setCategory: 'Set category', setProject: 'Set project', loadMore: 'Load more',
    conflict: 'Changed by someone else — reloaded, please review and save again', costType: 'Cost type',
    defaultCostType: 'default', sign: 'Money out', signIn: 'Money in', inferred: 'awaiting statement',
  },
  imp: {
    upload: 'Upload a statement', drop: 'Drop a bank export here (MT940, ABN XLS, bunq CSV, ICS PDF)',
    source: 'Source', autodetect: 'Auto-detect', batches: 'Imports', rows: 'Rows', review: 'Review',
    accept: 'Accept', skip: 'Skip', acceptSelected: 'Accept selected', acceptHigh: 'Accept high confidence',
    acceptRules: 'Accept all rule-matched', commit: 'Commit', commitConfirm: 'Commit {{count}} rows to the ledger?',
    suggest: 'Ask AI', aiUnavailable: 'AI is not configured on the server (no API key)',
    discard: 'Discard batch', confidence: 'Confidence', rule: 'Rule', suggestion: 'Suggestion', duplicate: 'Duplicate',
    committed: '{{count}} rows committed', errors: '{{count}} rows need attention', sheet: 'Google Sheet (history)',
    sheetHelp: 'Upload the xlsx export of the budget workbook. Choose years or leave empty for all.',
    years: 'Years', anchors: 'Load year-end balances', balancing: 'Generate balancing', migration: 'History migration',
    status: { new: 'New', suggested: 'Suggested', accepted: 'Accepted', skipped: 'Skipped', duplicate: 'Duplicate', committed: 'Committed' },
    showDone: 'Show committed / skipped', statementCheck: 'Statement balance check',
  },
  budget: {
    plan: 'Plan', actual: 'Actual', remaining: 'Remaining', template: 'Monthly template', generate: 'Fill from template',
    addLine: 'Add plan line', validFrom: 'Valid from', validTo: 'Valid to', unplanned: 'Unplanned', over: 'Over budget',
  },
  wealth: {
    reconcile: 'Reconcile', statedBalance: 'Balance at bank', difference: 'Difference', lastReconciled: 'Last reconciled',
    outstanding: 'Outstanding', original: 'Original', repaidYtd: 'Repaid this year', interestYtd: 'Interest this year',
    payoff: 'Payoff', parts: 'Loan parts', rate: 'Rate', schedule: 'Schedule', addValuation: 'Add valuation',
    valuedOn: 'valued on', holdings: 'Holdings', invested: 'Invested', gain: 'Gain', target: 'Target',
    identifiers: 'Identifiers', openingDate: 'Opening date', openingBalance: 'Opening balance', term: 'Term (months)',
    ratePeriods: 'Rate periods', lenderPattern: 'Lender match (IBAN or regex)', snapshot: 'Balance snapshot',
    newAccount: 'New account', newDebt: 'New debt', newAsset: 'New asset', newProject: 'New project', newEarmark: 'New earmark',
    budgetUsed: 'of budget',
  },
  settings: {
    profile: 'Profile', categories: 'Categories', users: 'Users', fx: 'Exchange rates', ai: 'AI', rules: 'Import rules',
    data: 'Data', language: 'Language', numberStyle: 'Number format', password: 'Change password',
    currentPassword: 'Current password', newPassword: 'New password', twofa: 'Two-factor authentication',
    enable2fa: 'Enable', disable2fa: 'Disable', scan: 'Scan with your authenticator app, then enter a code',
    newCategory: 'New category', merge: 'Merge into…', aiHint: 'Hint for the AI', fetchFx: 'Fetch rates now',
    model: 'Model', usage: 'Usage this month', export: 'Export', cutover: 'Bank statements from',
    cardCutover: 'Card statements from', historyStart: 'History starts',
  },
}

type Dict = typeof en

const ru: Dict = {
  nav: {
    dashboard: 'Сводка', year: 'Год', transactions: 'Операции', import: 'Импорт', budget: 'Бюджет', wealth: 'Капитал',
    accounts: 'Счета', debts: 'Долги', assets: 'Активы и инвестиции', earmarks: 'Отложено детям', projects: 'Проекты',
    settings: 'Настройки',
  },
  common: {
    add: 'Добавить', save: 'Сохранить', cancel: 'Отмена', delete: 'Удалить', edit: 'Изменить', close: 'Закрыть',
    search: 'Поиск', loading: 'Загрузка…', none: 'Нет', total: 'Итого', all: 'Все', date: 'Дата', amount: 'Сумма',
    account: 'Счёт', category: 'Категория', subcategory: 'Подкатегория', description: 'Описание', notes: 'Заметки',
    project: 'Проект', kind: 'Тип', currency: 'Валюта', name: 'Название', type: 'Тип', status: 'Статус', from: 'С',
    to: 'По', month: 'Месяц', income: 'Доходы', expenses: 'Расходы', balance: 'Баланс', saved: 'Сохранено',
    error: 'Ошибка', reference: 'EUR', native: '€ + ₽', logout: 'Выйти', table: 'Таблица', chart: 'График',
    apply: 'Применить', archive: 'В архив', value: 'Стоимость', actions: 'Действия', yes: 'Да', no: 'Нет',
    retry: 'Повторить', nothing: 'Пока ничего нет',
  },
  kinds: {
    expense: 'Расход', income: 'Доход', transfer: 'Перевод', debt_payment: 'Платёж по долгу', debt_drawdown: 'Получение займа',
    investment: 'Инвестиция', asset_purchase: 'Покупка актива', earmark: 'Отложено', adjustment: 'Корректировка', mixed: 'Смешанная',
  },
  costType: { fixed: 'Постоянные', variable: 'Переменные', one_time: 'Разовые' },
  login: { title: 'Вход', email: 'E-mail', password: 'Пароль', totp: 'Код из приложения', submit: 'Войти' },
  dash: {
    costsByCategory: 'Расходы по категориям', costsByType: 'Расходы по типу', incomeByCategory: 'Доходы по категориям',
    budget: 'План и факт', balances: 'Остатки на счетах', netWorth: 'Капитал', bridge: 'Изменение за месяц',
    cashFlow: 'Денежный поток', vsPrev: 'к прошлому месяцу', vsAvg: 'к среднему за 12 мес.', available: 'Свободные средства',
    alerts: 'Требует внимания', reviewImports: '{{count}} строк импорта ждут проверки',
    estimatedFx: 'Часть сумм посчитана по приблизительному курсу', principal: 'Погашено тела долга',
    toInvest: 'В инвестиции', noData: 'В этом месяце операций пока нет',
    funds: 'Средства', investments: 'Инвестиции', assets: 'Активы', debts: 'Долги',
    bridgeParts: {
      income: 'Доходы', expenses: 'Расходы', adjustments: 'Корректировки', conversion_cost: 'Потери на конвертации',
      asset_revaluation: 'Переоценка активов', investment_gain: 'Доход от инвестиций', debt_corrections: 'Корректировки долгов',
      fx_revaluation_and_rounding: 'Курсовая переоценка',
    },
  },
  year: { months: 'Месяцы', categories: 'Категории', avg: 'в среднем / мес.', heatmap: 'Расходы по категориям и месяцам', funds: 'Средства (конец)' },
  txn: {
    new: 'Новая операция', editTitle: 'Изменить операцию', split: 'Разбить', addSplit: 'Добавить строку', remaining: 'Остаток',
    fromAccount: 'Со счёта', toAccount: 'На счёт', amountOut: 'Списано', amountIn: 'Зачислено', impliedRate: 'Курс сделки',
    marketRate: 'Рыночный курс', debt: 'Долг', interest: 'Проценты', principal: 'Тело', suggest: 'Предложить разбивку',
    saveAndNew: 'Сохранить и ещё', deleted: 'Операция удалена', earmark: 'Кому', allocate: 'Отложить', release: 'Потратить',
    security: 'Бумага', units: 'Кол-во', price: 'Цена', fees: 'Комиссия', buy: 'Покупка', sell: 'Продажа', filters: 'Фильтры',
    uncategorised: 'Только без категории', bulk: 'Выбрано: {{count}}', setCategory: 'Задать категорию',
    setProject: 'Задать проект', loadMore: 'Загрузить ещё',
    conflict: 'Кто-то изменил операцию — данные обновлены, проверьте и сохраните снова', costType: 'Тип расхода',
    defaultCostType: 'по умолчанию', sign: 'Списание', signIn: 'Поступление', inferred: 'ждёт выписки',
  },
  imp: {
    upload: 'Загрузить выписку', drop: 'Перетащите выгрузку банка (MT940, ABN XLS, bunq CSV, ICS PDF)',
    source: 'Источник', autodetect: 'Определить автоматически', batches: 'Импорты', rows: 'Строки', review: 'Проверка',
    accept: 'Принять', skip: 'Пропустить', acceptSelected: 'Принять выбранные', acceptHigh: 'Принять уверенные',
    acceptRules: 'Принять по правилам', commit: 'Провести', commitConfirm: 'Провести {{count}} строк в учёт?',
    suggest: 'Спросить ИИ', aiUnavailable: 'ИИ не настроен на сервере (нет API-ключа)', discard: 'Отменить импорт',
    confidence: 'Уверенность', rule: 'Правило', suggestion: 'Предложение', duplicate: 'Дубликат',
    committed: 'Проведено строк: {{count}}', errors: 'Строк с ошибками: {{count}}', sheet: 'Google-таблица (история)',
    sheetHelp: 'Загрузите xlsx-выгрузку таблицы бюджета. Укажите годы или оставьте пустым для всех.',
    years: 'Годы', anchors: 'Загрузить остатки на конец года', balancing: 'Сгенерировать выравнивание',
    migration: 'Перенос истории',
    status: { new: 'Новая', suggested: 'Предложено', accepted: 'Принята', skipped: 'Пропущена', duplicate: 'Дубликат', committed: 'Проведена' },
    showDone: 'Показать проведённые / пропущенные', statementCheck: 'Сверка с остатком выписки',
  },
  budget: {
    plan: 'План', actual: 'Факт', remaining: 'Осталось', template: 'Шаблон месяца', generate: 'Заполнить из шаблона',
    addLine: 'Добавить строку плана', validFrom: 'Действует с', validTo: 'Действует по', unplanned: 'Вне плана',
    over: 'Превышение',
  },
  wealth: {
    reconcile: 'Сверить', statedBalance: 'Остаток в банке', difference: 'Разница', lastReconciled: 'Последняя сверка',
    outstanding: 'Остаток долга', original: 'Изначально', repaidYtd: 'Погашено в этом году', interestYtd: 'Проценты в этом году',
    payoff: 'Погашение', parts: 'Части кредита', rate: 'Ставка', schedule: 'График', addValuation: 'Добавить оценку',
    valuedOn: 'оценка на', holdings: 'Позиции', invested: 'Вложено', gain: 'Доход', target: 'Цель',
    identifiers: 'Идентификаторы', openingDate: 'Дата открытия', openingBalance: 'Начальный остаток', term: 'Срок (мес.)',
    ratePeriods: 'Периоды ставок', lenderPattern: 'Кредитор (IBAN или regex)', snapshot: 'Остаток по данным банка',
    newAccount: 'Новый счёт', newDebt: 'Новый долг', newAsset: 'Новый актив', newProject: 'Новый проект',
    newEarmark: 'Новая цель', budgetUsed: 'от бюджета',
  },
  settings: {
    profile: 'Профиль', categories: 'Категории', users: 'Пользователи', fx: 'Курсы валют', ai: 'ИИ', rules: 'Правила импорта',
    data: 'Данные', language: 'Язык', numberStyle: 'Формат чисел', password: 'Сменить пароль',
    currentPassword: 'Текущий пароль', newPassword: 'Новый пароль', twofa: 'Двухфакторная защита', enable2fa: 'Включить',
    disable2fa: 'Отключить', scan: 'Отсканируйте в приложении-аутентификаторе и введите код', newCategory: 'Новая категория',
    merge: 'Объединить с…', aiHint: 'Подсказка для ИИ', fetchFx: 'Загрузить курсы', model: 'Модель',
    usage: 'Использование в этом месяце', export: 'Экспорт', cutover: 'Банковские выписки с',
    cardCutover: 'Выписки по карте с', historyStart: 'История с',
  },
}

i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, ru: { translation: ru } },
  lng: (() => {
    try {
      return localStorage.getItem('budget.lang') || 'en'
    } catch {
      return 'en'
    }
  })(),
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

export default i18n
