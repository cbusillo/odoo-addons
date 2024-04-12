/** @odoo-module **/
import { Component, onMounted, onPatched, useState } from '@odoo/owl'
import { useService } from '@web/core/utils/hooks'
import { registry } from '@web/core/registry'
import { groupBy, sortBy } from '@web/core/utils/arrays'
import {
  BadgeSelectionField,
} from '@web/views/fields/badge_selection/badge_selection_field'
import { FloatField } from '@web/views/fields/float/float_field'
import { CharField } from '@web/views/fields/char/char_field'
import { BinaryField } from '@web/views/fields/binary/binary_field'
import { PdfViewerField } from '@web/views/fields/pdf_viewer/pdf_viewer_field'

/**
 * @typedef {Object} ConditionalTest
 * @property {string} data.conditional_test - The name of the conditional test.
 * @property {string} data.hidden_tests - The type of action for the conditional test.
 */
/**
 * @typedef {Object} MotorTestRecord
 * @property {string} data.result_type - The type of the result.
 * @property {Array<ConditionalTest>} data.conditional_tests - The conditional tests for the result.
 * @property {number} data.section_sequence - The sequence of the section.
 */
export class MotorTestWidget extends Component {
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

    // onPatched(() => {
    //   if (this.shouldReloadTests(this.allTests)) {
    //     this.loadMotorTests()
    //   }
    // })
  }

  async onFieldChanged(event) {
    console.log('Field changed:', event)
    await this.loadMotorTests()
  }

  async loadMotorTests() {
    const { name, record } = this.props
    this.allTests = record.data[name].records
    const missingParts = record.data.parts.records.filter(
      (part) => part.data.missing,
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
          condition.conditional_test[0],
          condition,
        ]),
      )

      const sortedTests = this.sortMotorTests(this.allTests)
      console.log('Before update:', this.motorTestsBySection)
      this.motorTestsBySection.sections = this.groupMotorTestsBySection(
        sortedTests,
        missingParts,
      )
      console.log('After update:', this.motorTestsBySection)
    } catch (error) {
      console.error('Error loading motor tests:', error)
    }
  }

  shouldReloadTests(currentTests) {
    for (const test of currentTests) {
      if (test._changes && Object.keys(test._changes).length > 0) {
        return true
      }
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
    // Check if the test is hidden by missing parts
    const hiddenByParts = missingParts.some((part) =>
      part.data.hidden_tests.currentIds.includes(test.data.template[0]),
    )
    if (hiddenByParts) {
      console.log('Test hidden by missing parts:', test.data.name)
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

    const hideConditionsMet = hideConditions.some((condition) => {
      const templateTest = this.allTests.find(
        (t) => t.data.template[0] === condition.template[0],
      )
      if (templateTest) {
        const resultType = templateTest.data.result_type
        const result = templateTest.data[`${resultType}_result`]
        return this.evaluateCondition(result, resultType, condition)
      }
      return false
    })

    console.log(
      'Conditions met for test:',
      test.data.name,
      'Hide:',
      hideConditionsMet,
    )

    if (hideConditionsMet) {
      return false
    }

    const showConditions = test.data.conditional_tests.records.map(
      (condition) => {
        const conditionRecord = this.conditionsById[condition.data.id]
        if (conditionRecord && conditionRecord.action_type === 'show') {
          return conditionRecord
        }
        return null
      }).filter(Boolean)

    const showConditionsMet = showConditions.every((condition) => {
      const templateTest = this.allTests.find(
        (t) => t.data.template[0] === condition.template[0],
      )
      if (templateTest) {
        const resultType = templateTest.data.result_type
        const result = templateTest.data[`${resultType}_result`]
        return this.evaluateCondition(result, resultType, condition)
      }
      return true
    })

    console.log(
      'Conditions met for test:',
      test.data.name,
      'Show:',
      showConditionsMet,
    )

    if (showConditions.length > 0) {
      return showConditionsMet
    }
    return true
  }

  evaluateCondition(result, resultType, condition) {
    const conditionRecord = Object.values(this.conditionsById).find(
      (c) => c.id === condition.id,
    )

    const { condition_value: conditionValue } = conditionRecord

    let conditionMet = false

    if (resultType === 'selection') {
      conditionMet = result.toLowerCase() === conditionValue.toLowerCase()
    } else if (resultType === 'numeric') {
      conditionMet = parseFloat(result) > parseFloat(conditionValue)
    } else if (resultType === 'yes_no') {
      conditionMet = result.toLowerCase() === conditionValue.toLowerCase()
    }
    console.log('Condition evaluation:', condition, conditionMet)
    return conditionMet
  }

  setSelectionFieldDomain({
    data: { result_type: resultType, selection_options: selectionOptions },
    id,
  }) {
    if (resultType === 'selection') {
      this.selectionFieldDomains[id] = [
        ['id', '=', selectionOptions.currentIds],
      ]
    }
  }

  // noinspection JSUnusedGlobalSymbols
  getSelectionFieldDomain(testId) {
    return this.selectionFieldDomains[testId] || []
  }
}

MotorTestWidget.template = 'product_connect.MotorTestWidget'
MotorTestWidget.components = {
  BadgeSelectionField,
  FloatField,
  CharField,
  BinaryField,
  PdfViewerField,
}

export const motorTestWidget = {
  component: MotorTestWidget,
}

registry.category('fields').add('motor_test_widget', motorTestWidget)
