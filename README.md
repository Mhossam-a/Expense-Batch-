# Expense Batch — دفعات مطالبات المصروفات

أدخل عشرات الفواتير دفعة واحدة، وشاهد كيف ستنقسم إلى مطالبات مصروفات (Expense Claim) منفصلة قبل إنشائها.
كل فاتورة تحمل تاريخها وضريبتها ومرفقها، ويمكن أن يكون لكل نوع مصروف حساب دائنين خاص به.

*Enter many invoices at once, preview how they split into separate Expense Claims, then create them.
Each invoice keeps its own date, tax and attachment, and each expense type can post to its own payable account.*

## ماذا يفعل

| الحاجة | كيف يحلّها التطبيق |
|---|---|
| عدة فواتير لنفس الموظف بتواريخ مختلفة | جدول إدخال سريع؛ كل فاتورة (أو يوم، أو موظف) تصبح مطالبة مستقلة |
| معرفة أي سطر عليه ضريبة | عمود **Has Tax** في جدول المصروفات (في الدفعة وفي Expense Claim نفسها)، مع قالب الضريبة ومبلغها لكل سطر |
| ضريبة على بعض الفواتير دون غيرها | الضريبة تأتي من Item Tax Template وتُحفظ **مبلغاً** لا نسبة، وتُجمَّع في جدول الضريبة حسب الحساب ومركز التكلفة والمشروع |
| المرفقات | مرفق كل فاتورة يُنقل تلقائياً إلى مطالبتها (دون نسخ الملف على القرص) |
| فلاتر الشركة | الحسابات ومراكز التكلفة (الفرعية فقط) والمشاريع وقوالب الضريبة وأنواع المصروف تُفلتر بشركة المستند |
| حساب دائنين مختلف لكل نوع مصروف | حقل `default_payable_account` داخل جدول الحسابات في Expense Claim Type، لكل شركة |
| الإدخال اليدوي في Expense Claim | نفس منطق الضريبة وحساب الدائنين، مع منع الجمع بين أنواع تُرحَّل لحسابات مختلفة |

## المتطلبات والإصدارات

- Frappe و ERPNext و HRMS، الإصدار **15 أو 16**.
- **اختُبر على** (تثبيت جديد، توليد مباشر وفي الخلفية، قيود الأستاذ، الإلغاء والتعديل والنسخ، الصلاحيات):
  - Frappe 15.121 / ERPNext 15 / HRMS 15
  - Frappe 16.36 / ERPNext 16.37 / HRMS 16.20
- الواجهة (خريطة التقسيم، الأزرار، الفلاتر) فُحصت ببيئة محاكاة للمتصفح (jsdom) وليس بمتصفح حقيقي. راجع الشاشة بنفسك عند أول استخدام.
- المطالبات متعددة العملات (ميزة HRMS 16) غير مدعومة: التطبيق يُنشئ المطالبات بعملة الشركة.

## التثبيت

```bash
bench get-app https://github.com/Mhossam-a/expense_batch
bench --site <your-site> install-app expense_batch
bench --site <your-site> migrate
```

### على Frappe Cloud

1. **Apps ← Add App ← From GitHub** واختر `Mhossam-a/expense_batch` (الفرع `main`). إن كان المستودع خاصاً فامنح Frappe Cloud إذن الوصول لحسابك من الشاشة نفسها.
2. افتح الـ Bench (يجب أن يكون الإصدار 16 وعليه ERPNext وHRMS) وأضف التطبيق، ثم **Deploy**.
3. من الموقع: **Apps ← Install App** واختر Expense Batch.

## الإعداد لمرة واحدة

1. **Expense Claim Type** ← جدول الحسابات (Accounts): بجانب حساب المصروف، اختر **Default Payable Account** لكل شركة.
2. **Expense Batch Settings**:
   - أبقِ «الرجوع لحساب الشركة» مُعطّلاً إن أردت إلزام كل نوع بحسابه (هذا هو الافتراضي).
   - أضف قالب الضريبة الافتراضي لكل شركة، فيُملأ تلقائياً عند تحديد **Has Tax**.
3. لكل شركة: Item Tax Template فيه حساب الضريبة ونسبتها.

## الاستخدام

1. أنشئ **Expense Claim Batch**، اختر الشركة والموظف الافتراضي (ومركز التكلفة والمشروع إن لزم).
2. أضف الفواتير في الجدول. السطر الجديد ينسخ تاريخ ونوع ومركز تكلفة السطر الذي فوقه. زر **Bulk edit rows** يعدّل عدة صفوف دفعة واحدة.
3. تابع **خريطة التقسيم**: شريط يقسّم الدفعة إلى مطالبات حسب المبلغ، وتحته بطاقة لكل مطالبة، وقائمة بما يحتاج تصحيحاً.
4. اختر طريقة التقسيم من الأزرار أعلى الخريطة.
5. **Submit** للدفعة (لا يُسمح بالاعتماد وفي الصفوف أخطاء).
6. اضغط **Generate Expense Claims**. المطالبات تُنشأ **مسودات** لتراجعها ثم تعتمدها من القائمة.

### طرق التقسيم

- **مطالبة لكل فاتورة** (الافتراضي): كل فاتورة قيد منفصل في الأستاذ.
- **موظف + تاريخ**: فواتير الموظف في اليوم نفسه في مطالبة واحدة.
- **موظف**: مطالبة واحدة لكل موظف.

في الطريقتين الأخيرتين تنفصل الفواتير تلقائياً إن كان حساب الدائنين مختلفاً، لأن المطالبة الواحدة لها حساب دائنين واحد فقط.

### الضريبة

- **Has Tax** مع قالب: الضريبة تُحسب من حسابات ونسب القالب. **Has Tax** دون قالب يأخذ قالب الشركة الافتراضي، فإن لم يوجد يُرفض الحفظ برسالة واضحة. القالب وحده يُفعّل Has Tax.
- القالب يجب أن يتبع شركة المستند وأن يكون غير معطّل، وإلا يُرفض الحفظ.
- الافتراضي: الضريبة **تُضاف** فوق المبلغ المُدخل.
- خانة «مبالغ الفواتير شاملة الضريبة» (في الدفعة): المبلغ المُدخل هو إجمالي الفاتورة، وتُستخرج الضريبة منه. إجمالي المطالبة يطابق الفاتورة إلى آخر خانة عشرية.
- التقريب: الكسر .5 يُقرَّب للأعلى.
- الصفوف التي تكتبها بيدك في جدول الضريبة لا تُمس. الصفوف التي أضافها التطبيق تُعاد حسابها عند كل حفظ.
- المطالبات المعتمدة والملغاة لا يُعاد حسابها أبداً.

### بعد التوليد

- الصفوف التي أنتجت مطالبة **تُقفل**. لتعديلها احذف مطالبتها أو ألغها أولاً.
- حذف مطالبة مسودة يعيد صفّها إلى «قيد الانتظار». إلغاء مطالبة معتمدة يضع صفّها «ملغى» ويمكن إعادة توليده.
- زر **Delete draft claims** يتراجع عن كل المسودات دفعة واحدة (يحتاج صلاحية حذف Expense Claim)، ولا يمس المعتمدة.
- لا يمكن إلغاء الدفعة قبل إلغاء/حذف مطالباتها. بعد الإلغاء يعمل **Amend** وتبدأ الصفوف نظيفة.
- الدفعات الكبيرة (أكثر من 15 مطالبة افتراضياً) تُنشأ في الخلفية مع شريط تقدم، ويلزم أن يعمل الـ worker.

### الصلاحيات

المستخدم الذي يولّد المطالبات يحتاج صلاحية **إنشاء Expense Claim** (أدوار HR User و HR Manager تكفي)، لأن التطبيق ينشئها باسمه ولا يتجاوز الصلاحيات.

## الإدخال اليدوي في Expense Claim

يضيف التطبيق إلى كل سطر مصروف: **Has Tax** و **Item Tax Template** و **Tax Amount**. تُجمَّع ضرائب الأسطر في جدول الضريبة. حساب الدائنين يُملأ من نوع المصروف، وإن اختلفت الأنواع في حساباتها يُرفض الحفظ برسالة واضحة. يمكن تعطيل ذلك للمطالبات اليدوية من **Expense Batch Settings**.

> في الإصدار 15 يعرض الجدول 10 وحدات عرض كحد أقصى، فقد يُخفي عمود **Has Tax** عموداً آخر. استخدم أيقونة الترس في الجدول لإعادة ترتيب الأعمدة. في الإصدار 16 يظهر الجميع مع تمرير أفقي.

## ما يضيفه التطبيق إلى النظام

حقول مخصصة (تُنشأ عند التثبيت والـ migrate، وتُحذف عند إلغاء التثبيت):

- `Expense Claim Account.default_payable_account`
- `Expense Claim Detail.has_tax`, `item_tax_template`, `line_tax_amount`
- `Expense Taxes and Charges.from_item_tax_template` (مخفي، يميّز الصفوف التي أضافها التطبيق)
- `Expense Claim.expense_batch` (رابط للدفعة)

وأربعة DocTypes جديدة، وتعديلات `doc_events` على Expense Claim (قبل التحقق، قبل الإلغاء، عند الإلغاء، عند الحذف). لا يغيّر التطبيق شيئاً في كود HRMS نفسه.

## حدود معروفة

- Expense Claim في HRMS يُرحّل حساب دائنين **واحد** لكل مطالبة؛ لذلك لا يمكن الجمع بين نوعين بحسابين مختلفين في مطالبة واحدة.
- مبلغ المطالبة اليدوية يُعامل كصافٍ قبل الضريبة (سلوك HRMS)؛ خيار «شامل الضريبة» متاح في الدفعات فقط.
- الاعتماد التلقائي للمطالبات غير مدعوم عمداً: تراجع المسودات ثم تعتمدها.
- حذف مطالبة معتمدة وملغاة غير ممكن (قاعدة ERPNext بسبب قيود الأستاذ).

---

## English summary

**What:** a batch entry screen for Expense Claims. One invoice row becomes one claim (or one per employee/day, or per employee).

**Key behaviours**
- A **Has Tax** column on every expense row (batch and Expense Claim), with the Item Tax Template and the tax amount of that row.
- Tax is stored as an amount, grouped per account / cost center / project. Optional tax-inclusive entry; the claim total equals the invoice total to the cent.
- Company filters everywhere: cost centers (ledger only), projects, tax templates, employees and expense types are limited to the document's company.
- Attachment on a row is linked to its claim (same stored file, no duplicate on disk).
- Payable account per Expense Claim Type per company, instead of one on the Company. Mixed types in one manual claim are rejected.
- *Split Map*: live preview of the claims before anything is created, with a proportional bar, per-claim cards and row-level problems.
- Generation is savepoint-protected per claim; large batches run as a background job with live progress.
- Generated rows are locked; deleting/cancelling a claim updates its batch row. Cancel and Amend work on batches.

**Tested** on Frappe 15.121 / ERPNext 15 / HRMS 15 and Frappe 16.36 / ERPNext 16.37 / HRMS 16.20. The UI was exercised in a simulated browser (jsdom), not a real one.

**Install**
```bash
bench get-app https://github.com/Mhossam-a/expense_batch
bench --site <site> install-app expense_batch
```

MIT licensed.
