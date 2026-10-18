// Reads a whole cube query result in one call, so Python does not have to ask .NET for every value
// (see ssas.py, run_query). Build with build.ps1; the compiled AdomdBulk.dll sits next to this file.
//
// It only uses the standard IDataReader interface, so it works with any version of ADOMD.NET.
//
// The result is one JSON text, column by column:
//   {"format": 1, "complete": true, "rows": 2, "columns": ["Calendar[Year]", "[Sale]"],
//    "types": ["System.Int64", "System.Object"], "data": [[2025, 2026], [10.5, null]]}
// Values are written exactly as Python's row reader (pyadomd) turns them into Python values:
//   - text: a JSON string; empty text in a text column becomes null (pyadomd does the same)
//   - whole numbers: JSON integers; decimal numbers and money: JSON numbers with a decimal point,
//     17 significant digits so the number comes back bit for bit (NaN / Infinity / -Infinity as such)
//   - dates: "yyyy-MM-ddTHH:mm:ss" (pyadomd drops fractions of a second too)
//   - true/false: JSON true/false; empty cells: null
// When a row holds a value it can't write the same way (e.g. a .NET date inside a measure column),
// it stops before that row with "complete": false. The reader then stands on that row, and Python
// reads it and the rest one by one, so the result is still exactly what the row reader gives.
using System;
using System.Data;
using System.Globalization;
using System.Text;

namespace AdomdBulk
{
    public static class BulkReader
    {
        // Python checks this before using the reader; change it whenever the output changes.
        public const int FormatVersion = 1;

        private enum Kind { Text, Guid, Boolean, Whole, Real, Money, Date, Any, Unknown }

        private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;

        // Reads up to maxRows rows (0 = all) from an open reader and returns them as JSON text.
        public static string Read(IDataReader reader, int maxRows)
        {
            int n = reader.FieldCount;
            string[] names = new string[n];
            string[] types = new string[n];
            Kind[] kinds = new Kind[n];
            StringBuilder[] columns = new StringBuilder[n];
            for (int i = 0; i < n; i++)
            {
                Type type = reader.GetFieldType(i);
                names[i] = reader.GetName(i);
                types[i] = type == null ? "" : type.ToString();
                kinds[i] = KindOf(types[i]);
                columns[i] = new StringBuilder();
            }

            string[] cells = new string[n];
            int rows = 0;
            bool complete = true;
            while ((maxRows <= 0 || rows < maxRows) && reader.Read())
            {
                if (!EncodeRow(reader, kinds, cells))
                {
                    complete = false;  // Python reads this row and the rest one by one
                    break;
                }
                for (int i = 0; i < n; i++)
                {
                    if (rows > 0) columns[i].Append(',');
                    columns[i].Append(cells[i]);
                }
                rows++;
            }
            return Assemble(complete, rows, names, types, columns);
        }

        private static Kind KindOf(string type)
        {
            switch (type)
            {
                case "System.String": return Kind.Text;
                case "System.Guid": return Kind.Guid;
                case "System.Boolean": return Kind.Boolean;
                case "System.Int16":
                case "System.Int32":
                case "System.Int64":
                case "System.UInt16":
                case "System.UInt32":
                case "System.UInt64": return Kind.Whole;
                case "System.Double":
                case "System.Single": return Kind.Real;
                case "System.Decimal": return Kind.Money;
                case "System.DateTime": return Kind.Date;
                case "System.Object": return Kind.Any;
                default: return Kind.Unknown;
            }
        }

        // Writes every value of the current row into cells; false if one can't be written exactly.
        private static bool EncodeRow(IDataReader reader, Kind[] kinds, string[] cells)
        {
            for (int i = 0; i < kinds.Length; i++)
            {
                cells[i] = Encode(kinds[i], reader.GetValue(i));
                if (cells[i] == null) return false;
            }
            return true;
        }

        // One value as JSON, or null when it has to be read by Python's row reader instead.
        private static string Encode(Kind kind, object value)
        {
            if (value == null) return "null";
            if (value is DBNull) return null;
            switch (kind)
            {
                case Kind.Text:
                    string text = value as string;
                    if (text == null) return null;
                    return text.Length == 0 ? "null" : Quote(text);
                case Kind.Guid:
                    return value is Guid ? Quote(value.ToString()) : null;
                case Kind.Boolean:
                    return value is bool ? ((bool)value ? "true" : "false") : null;
                case Kind.Whole:
                    return IsWhole(value) ? ((IFormattable)value).ToString(null, Invariant) : null;
                case Kind.Real:
                    if (value is double) return Real((double)value);
                    if (value is float) return Real((double)(float)value);
                    return null;
                case Kind.Money:
                    return value is decimal ? Real(decimal.ToDouble((decimal)value)) : null;
                case Kind.Date:
                    return value is DateTime ? Quote(((DateTime)value).ToString("yyyy-MM-dd'T'HH:mm:ss", Invariant)) : null;
                case Kind.Any:
                    return EncodeAny(value);
                default:
                    return null;
            }
        }

        // A value in an untyped column (measures): only the kinds Python receives as plain values.
        private static string EncodeAny(object value)
        {
            string text = value as string;
            if (text != null) return Quote(text);  // empty text stays empty here, as in pyadomd
            if (value is char) return Quote(value.ToString());
            if (value is bool) return (bool)value ? "true" : "false";
            if (IsWhole(value) || value is byte || value is sbyte) return ((IFormattable)value).ToString(null, Invariant);
            if (value is double) return Real((double)value);
            if (value is float) return Real((double)(float)value);
            return null;
        }

        private static bool IsWhole(object value)
        {
            return value is long || value is int || value is short || value is ulong || value is uint || value is ushort;
        }

        // A number Python reads back as the very same float.
        private static string Real(double value)
        {
            if (double.IsNaN(value)) return "NaN";
            if (double.IsPositiveInfinity(value)) return "Infinity";
            if (double.IsNegativeInfinity(value)) return "-Infinity";
            if (value == 0) return BitConverter.DoubleToInt64Bits(value) < 0 ? "-0.0" : "0.0";  // keeps -0.0
            string text = value.ToString("G17", Invariant);
            return text.IndexOf('.') >= 0 || text.IndexOf('E') >= 0 ? text : text + ".0";
        }

        // Text as a JSON string. Surrogates are always escaped, so the transfer to Python is safe even
        // for broken text; Python joins valid pairs back into one character.
        private static string Quote(string text)
        {
            StringBuilder sb = new StringBuilder(text.Length + 2);
            sb.Append('"');
            foreach (char c in text)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < ' ' || (c >= '\uD800' && c <= '\uDFFF'))
                            sb.Append("\\u").Append(((int)c).ToString("x4", Invariant));
                        else
                            sb.Append(c);
                        break;
                }
            }
            return sb.Append('"').ToString();
        }

        private static string Assemble(bool complete, int rows, string[] names, string[] types, StringBuilder[] columns)
        {
            int size = 128;
            foreach (StringBuilder column in columns) size += column.Length + 3;
            StringBuilder sb = new StringBuilder(size);
            sb.Append("{\"format\":").Append(FormatVersion.ToString(Invariant))
              .Append(",\"complete\":").Append(complete ? "true" : "false")
              .Append(",\"rows\":").Append(rows.ToString(Invariant))
              .Append(",\"columns\":[");
            for (int i = 0; i < names.Length; i++) sb.Append(i > 0 ? "," : "").Append(Quote(names[i] ?? ""));
            sb.Append("],\"types\":[");
            for (int i = 0; i < types.Length; i++) sb.Append(i > 0 ? "," : "").Append(Quote(types[i]));
            sb.Append("],\"data\":[");
            for (int i = 0; i < columns.Length; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append('[').Append(columns[i]).Append(']');
            }
            return sb.Append("]}").ToString();
        }
    }
}
