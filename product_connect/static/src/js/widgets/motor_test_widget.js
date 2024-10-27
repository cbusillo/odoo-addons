/** @odoo-module **/
import { Component, onMounted, onWillUpdateProps, useState } from '@odoo/owl'
import { useService } from '@web/core/utils/hooks'
import { registry } from '@web/core/registry'
import { groupBy, sortBy } from '@web/core/utils/arrays'
import { ResettableBadgeSelectionField, } from './resettable_badge_selection_widget.js'
import { FloatField } from '@web/views/fields/float/float_field'
import { CharField } from '@web/views/fields/char/char_field'
import { BinaryField } from '@web/views/fields/binary/binary_field'
import { PdfViewerField } from '@web/views/fields/pdf_viewer/pdf_viewer_field'

/**
 * @typedef {Object} ConditionalTest
 * @property {string} data.conditional_test
 * @property {string} data.action_type
 * @property {string} data.hidden_tests
 /**
 * @typedef {Object} MotorTestRecord
 * @property {string} data.result_type
 * @property {Array<ConditionalTest>} data.conditional_tests
 * @property {number} data.section_sequence
 * @property {Array<int>} data.manufacturers
 * @property {Array<int>} data.configurations
 */
/**
 * @typedef {Object} MotorPartRecord
 * @property {boolean} data.is_missing
 */
export class MotorTestWidget extends Component {
    static template = 'product_connect.MotorTestWidget'
    static components = {
        ResettableBadgeSelectionField,
        FloatField,
        CharField,
        BinaryField,
        PdfViewerField,
    }
    static props = {
        id: String,
        name: String,
        record: Object,
        readonly: Boolean,
    }

    async setup() {
        this.motorTestsBySection = useState({ sections: [] })
        this.selectionFieldDomains = useState({})
        this.conditionsById = {}
        this.allTests = []
        this.orm = useService('orm')

        onMounted(() => {
            this.loadMotorTests()
        })

        onWillUpdateProps((nextProps) => {
            if (nextProps.record !== this.props.record) {
                this.loadMotorTests(nextProps)
            }
        })
    }

    async onFieldChanged() {
        await this.props.record.save()
        await this.loadMotorTests()
    }

    async loadMotorTests(props = this.props) {
        const { name, record } = props
        this.allTests = record.data[name].records
        const missingParts = record.data.parts.records.filter(
            (part) => part.data.is_missing,
        )

        const conditionIds = this.allTests.flatMap(
            (record) => record.data.conditions.currentIds,
        )

        try {
            const conditions = await this.orm.searchRead(
                'motor.test.template.condition',
                [['id', 'in', conditionIds]],
                ['action_type', 'condition_value', 'template', 'conditional_test'],
            )

            this.conditionsById = Object.fromEntries(
                conditions.map((condition) => [
                    condition.id,
                    condition,
                ]),
            )

            const sortedTests = this.sortMotorTests(this.allTests)
            this.motorTestsBySection.sections = this.groupMotorTestsBySection(
                sortedTests,
                missingParts,
            )
        } catch (error) {
            console.error('Error loading motor tests:', error)
        }
    }

    sortMotorTests(motorTests) {
        return sortBy(motorTests, (test) => [
            test.data.section_sequence || 0,
            test.data.sequence || 0,
        ])
    }

    groupMotorTestsBySection(motorTests, missingParts) {
        const groupedTests = groupBy(motorTests, (test) => test.data.section[1])

        return Object.entries(groupedTests).reduce((acc, [section, tests]) => {
            const filteredTests = tests.filter((test) => {
                const resultType = test.data.result_type
                const result = test.data[`${test.data.result_type}_result`]
                const isApplicable = this.evaluateTestApplicability(test, missingParts)
                if (!isApplicable) {
                    return false
                }

                const showConditions = test.data.conditions.records.filter(
                    (condition) => condition.data.action_type === 'show',
                )
                return showConditions.every((condition) =>
                    this.evaluateCondition(result, resultType, condition),
                )
            })

            const conditionalTests = filteredTests.flatMap((test) => {
                const resultType = test.data.result_type
                const result = test.data[`${test.data.result_type}_result`]

                return test.data.conditions.records.filter(
                    (conditionalTest) =>
                        conditionalTest.data &&
                        Object.keys(conditionalTest.data).length > 0 &&
                        this.evaluateCondition(result, resultType, conditionalTest),
                )
            })

            acc[section] = this.sortMotorTests([
                ...filteredTests,
                ...conditionalTests,
            ])

            for (const test of acc[section]) {
                this.setSelectionFieldDomain(test)
            }

            return acc
        }, {})
    }

    evaluateTestApplicability(test, missingParts) {
        const hiddenByParts = missingParts.some((part) =>
            part.data.hidden_tests.currentIds.includes(test.data.template[0]),
        )
        if (hiddenByParts) {
            return false
        }
        const motorManufacturerId = this.props.record.data.manufacturer[0]
        const testManufacturers = test.data.manufacturers.records.map(record => record.resId)
        const motorConfigurationId = this.props.record.data.configuration[0]
        const testConfigurations = test.data.configurations.records.map(record => record.resId)

        if (testManufacturers.length > 0 && !testManufacturers.includes(motorManufacturerId)) {
            return false
        }

        if (testConfigurations.length > 0 && testConfigurations.includes(motorConfigurationId)) {
            return false
        }

        const hideConditions = test.data.conditional_tests.records.map(
            (condition) => {
                const conditionRecord = Object.values(this.conditionsById).find(
                    (c) => c.id === condition.resId,
                )
                if (conditionRecord && conditionRecord.action_type === 'hide') {
                    return conditionRecord
                }
                return null
            }).filter(Boolean)

        const hideConditionsMet = hideConditions.some((condition) =>
            this.evaluateTemplateTestCondition(condition)
        )

        if (hideConditionsMet) {
            return false
        }

        const showConditions = test.data.conditional_tests.records.map(
            (condition) => {
                const conditionRecord = this.conditionsById[condition.resId]
                if (conditionRecord && conditionRecord.action_type === 'show') {
                    return conditionRecord
                }
                return null
            }).filter(Boolean)

        const showConditionsMet = showConditions.some((condition) =>
            this.evaluateTemplateTestCondition(condition)
        )

        if (showConditions.length > 0) {
            return showConditionsMet
        }
        return true
    }

    evaluateTemplateTestCondition(condition) {
        const templateTest = this.allTests.find(
            (t) => t.data.template[0] === condition.template[0],
        )
        if (templateTest) {
            const resultType = templateTest.data.result_type
            const result = resultType === 'selection' ?
                templateTest.data[`${resultType}_result_value`] : templateTest.data[`${resultType}_result`]
            return this.evaluateCondition(result, resultType, condition)
        }
        return false
    }

    evaluateCondition(result, resultType, condition) {
        const conditionRecord = Object.values(this.conditionsById).find(
            (c) => c.id === condition.id,
        )

        const { condition_value: conditionValue } = conditionRecord

        if (!result || !conditionValue) {
            return false
        } else if (resultType === 'selection') {
            return result.toLowerCase() === conditionValue.toLowerCase()
        } else if (resultType === 'numeric') {
            return parseFloat(result) > parseFloat(conditionValue)
        } else if (resultType === 'yes_no') {
            return result.toLowerCase() === conditionValue.toLowerCase()
        }
    }

    setSelectionFieldDomain({
                                data: { result_type: resultType, selection_options: selectionOptions },
                                id,
                            }) {
        if (resultType === 'selection') {
            this.selectionFieldDomains[id] = [
                ['id', 'in', selectionOptions.currentIds],
            ]
        }
    }

    // noinspection JSUnusedGlobalSymbols
    getSelectionFieldDomain(testId) {
        return this.selectionFieldDomains[testId] || []
    }
}


export const motorTestWidget = {
    component: MotorTestWidget,
}

registry.category('fields').add('motor_test_widget', motorTestWidget)
